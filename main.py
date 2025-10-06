from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
import asyncio
import logging
from datetime import datetime
import math

from config import BOT_TOKEN, ADMIN_IDS
from db import create_tables, SessionLocal, Category, Type, Product, ProductMedia, Cart, Order, OrderItem, \
    MainMenuSection
from admin import admin_router
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключаем админ-роутер
dp.include_router(admin_router)

# Константы для пагинации
ITEMS_PER_PAGE = 5


# Callback data классы для пагинации
class CategoryPagination(CallbackData, prefix="cat_pag"):
    page: int


class TypePagination(CallbackData, prefix="type_pag"):
    category_id: int
    page: int


class ProductPagination(CallbackData, prefix="prod_pag"):
    type_id: int
    page: int


# Callback data для навигации по медиа товара
class ProductMediaNavigation(CallbackData, prefix="prod_media"):
    product_id: int
    media_index: int
    type_id: int
    page: int


# Состояния для оформления заказа
class OrderState(StatesGroup):
    waiting_for_phone = State()


# Состояния для добавления в корзину
class CartState(StatesGroup):
    waiting_for_quantity = State()


# Словари для хранения сообщений
main_menu_messages = {}
user_last_messages = {}  # Хранит последние сообщения для каждого пользователя


async def cleanup_user_messages(chat_id: int, keep_main_menu: bool = True):
    """Удаляет все сообщения пользователя, кроме главного меню"""
    if chat_id in user_last_messages:
        for msg_id in user_last_messages[chat_id]:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}")
        user_last_messages[chat_id] = []

    if not keep_main_menu and chat_id in main_menu_messages:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=main_menu_messages[chat_id])
        except Exception as e:
            logger.debug(f"Не удалось удалить главное меню: {e}")
        del main_menu_messages[chat_id]


def add_user_message(chat_id: int, message_id: int):
    """Добавляет сообщение в список сообщений пользователя"""
    if chat_id not in user_last_messages:
        user_last_messages[chat_id] = []
    user_last_messages[chat_id].append(message_id)


async def update_main_menu(chat_id: int, text: str, reply_markup):
    """Обновляет главное меню или создает новое"""
    if chat_id in main_menu_messages:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=main_menu_messages[chat_id],
                text=text,
                reply_markup=reply_markup
            )
            return True
        except Exception as e:
            logger.debug(f"Не удалось обновить главное меню: {e}")
            try:
                await bot.delete_message(chat_id=chat_id, message_id=main_menu_messages[chat_id])
            except:
                pass
            del main_menu_messages[chat_id]

    return False


# Создание инлайн-клавиатуры для пользователей
def get_start_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="📁 Каталог", callback_data="catalog"),
         InlineKeyboardButton(text="🛠️ Услуги", callback_data="services")],
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"),
         InlineKeyboardButton(text="💬 Консультация", callback_data="consultation")],
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="cart")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Клавиатура для корзины
def get_cart_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="📋 Просмотр корзины", callback_data="view_cart")],
        [InlineKeyboardButton(text="🗑️ Очистить корзину", callback_data="clear_cart")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Клавиатура для товара с навигацией по медиа
def get_product_keyboard(product_id, type_id, page=0, media_index=0, media_count=1):
    keyboard = []

    # Кнопки навигации по медиа, если файлов больше одного
    if media_count > 1:
        nav_buttons = []
        if media_index > 0:
            nav_buttons.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=ProductMediaNavigation(
                    product_id=product_id,
                    media_index=media_index - 1,
                    type_id=type_id,
                    page=page
                ).pack()
            ))

        nav_buttons.append(InlineKeyboardButton(
            text=f"{media_index + 1}/{media_count}",
            callback_data="current_media"
        ))

        if media_index < media_count - 1:
            nav_buttons.append(InlineKeyboardButton(
                text="➡️",
                callback_data=ProductMediaNavigation(
                    product_id=product_id,
                    media_index=media_index + 1,
                    type_id=type_id,
                    page=page
                ).pack()
            ))

        keyboard.append(nav_buttons)

    # Основные кнопки действий
    keyboard.append(
        [InlineKeyboardButton(text="🛒 Добавить в корзину", callback_data=f"add_to_cart_{product_id}_{page}")])
    keyboard.append(
        [InlineKeyboardButton(text="🔙 Назад к товарам", callback_data=f"back_to_products_{type_id}_{page}")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Клавиатура после добавления в корзину
def get_after_cart_keyboard(type_id, page=0):
    keyboard = [
        [InlineKeyboardButton(text="🔙 Назад к товарам", callback_data=f"back_to_products_{type_id}_{page}")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Клавиатура для отмены ввода количества
def get_cancel_quantity_keyboard(product_id, type_id, page=0):
    keyboard = [
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_quantity_{product_id}_{type_id}_{page}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Клавиатура для просмотра корзины с итоговой суммой
def get_cart_summary_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton(text="🔄 Обновить корзину", callback_data="view_cart")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Клавиатура для удаления товара из корзины
def get_cart_item_keyboard(cart_item_id):
    keyboard = [
        [InlineKeyboardButton(text="❌ Удалить из корзины", callback_data=f"remove_from_cart_{cart_item_id}")],
        [InlineKeyboardButton(text="🔄 Обновить корзину", callback_data="view_cart")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    await cleanup_user_messages(chat_id, False)  # Полная очистка чата

    welcome_text = (
        "Добро пожаловать в магазин дверей! 🚪\n\n"
        "Выберите нужный раздел:"
    )

    # Создаем главное меню
    msg = await message.answer(welcome_text, reply_markup=get_start_keyboard())
    main_menu_messages[chat_id] = msg.message_id


# Обработчик нажатий на инлайн-кнопки (пользовательские)
@dp.callback_query(F.data.in_(["catalog", "services", "info", "consultation", "cart"]))
async def handle_callbacks(callback: types.CallbackQuery):
    data = callback.data
    chat_id = callback.message.chat.id
    await callback.answer()

    if data == "catalog":
        await show_catalog(callback, 0)
    elif data == "services":
        await show_main_menu_section(callback, "services")
    elif data == "info":
        await show_main_menu_section(callback, "info")
    elif data == "consultation":
        await show_main_menu_section(callback, "consultation")
    elif data == "cart":
        await show_cart_menu(callback)


# Показать раздел главного меню - ИСПРАВЛЕННАЯ ФУНКЦИЯ
async def show_main_menu_section(callback: types.CallbackQuery, section_key: str):
    chat_id = callback.message.chat.id
    await cleanup_user_messages(chat_id)  # Очищаем предыдущие сообщения

    db = SessionLocal()
    try:
        section = db.query(MainMenuSection).filter(MainMenuSection.section_key == section_key).first()
        if not section:
            # Если раздел не найден, показываем заглушку
            error_text = f"Раздел временно недоступен"
            if not await update_main_menu(chat_id, error_text, get_start_keyboard()):
                msg = await callback.message.answer(error_text, reply_markup=get_start_keyboard())
                main_menu_messages[chat_id] = msg.message_id
            return

        # Если есть фото, отправляем его с подписью
        if section.file_id and section.photo_path:
            try:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=section.file_id,
                    caption=section.content,
                    reply_markup=get_start_keyboard()
                )
                add_user_message(chat_id, msg.message_id)
            except Exception as e:
                # Если не удалось отправить фото, отправляем только текст
                logger.error(f"Ошибка отправки фото: {e}")
                if not await update_main_menu(chat_id, section.content, get_start_keyboard()):
                    msg = await callback.message.answer(section.content, reply_markup=get_start_keyboard())
                    main_menu_messages[chat_id] = msg.message_id
        else:
            # Если фото нет, просто обновляем текст
            if not await update_main_menu(chat_id, section.content, get_start_keyboard()):
                msg = await callback.message.answer(section.content, reply_markup=get_start_keyboard())
                main_menu_messages[chat_id] = msg.message_id

    except Exception as e:
        logger.error(f"Error showing section {section_key}: {e}")
        error_text = "Произошла ошибка при загрузке раздела"
        if not await update_main_menu(chat_id, error_text, get_start_keyboard()):
            msg = await callback.message.answer(error_text, reply_markup=get_start_keyboard())
            main_menu_messages[chat_id] = msg.message_id
    finally:
        db.close()


# Обработчик корзины
@dp.callback_query(F.data == "cart")
async def handle_cart(callback: types.CallbackQuery):
    await show_cart_menu(callback)
    await callback.answer()


# Показать меню корзины
async def show_cart_menu(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id

    # Обновляем главное меню для показа корзины
    if not await update_main_menu(chat_id, "🛒 Корзина\n\nВыберите действие:", get_cart_keyboard()):
        # Если не удалось обновить, создаем новое сообщение
        msg = await callback.message.answer("🛒 Корзина\n\nВыберите действие:", reply_markup=get_cart_keyboard())
        main_menu_messages[chat_id] = msg.message_id

# Показать каталог с пагинацией
async def show_catalog(callback: types.CallbackQuery, page: int = 0):
    chat_id = callback.message.chat.id
    await cleanup_user_messages(chat_id)  # Очищаем предыдущие сообщения

    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        if not categories:
            if not await update_main_menu(chat_id, "📁 Каталог пока пуст", get_start_keyboard()):
                msg = await callback.message.answer("📁 Каталог пока пуст", reply_markup=get_start_keyboard())
                main_menu_messages[chat_id] = msg.message_id
            return

        total_categories = len(categories)
        total_pages = math.ceil(total_categories / ITEMS_PER_PAGE)
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_categories = categories[start_idx:end_idx]

        builder = InlineKeyboardBuilder()
        for category in current_categories:
            builder.button(text=category.name, callback_data=f"show_category_{category.id}")

        # Добавляем кнопки пагинации
        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=CategoryPagination(page=page - 1).pack()
            ))
        if end_idx < total_categories:
            pagination_buttons.append(InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=CategoryPagination(page=page + 1).pack()
            ))

        if pagination_buttons:
            builder.row(*pagination_buttons)

        builder.button(text="🔙 Назад", callback_data="back_to_main")
        builder.adjust(1)

        text = f"📁 Выберите категорию:\n\nСтраница {page + 1} из {total_pages}"

        # Обновляем главное меню для показа каталога
        if not await update_main_menu(chat_id, text, builder.as_markup()):
            msg = await callback.message.answer(text, reply_markup=builder.as_markup())
            main_menu_messages[chat_id] = msg.message_id

    finally:
        db.close()


# Обработчик пагинации категорий
@dp.callback_query(CategoryPagination.filter())
async def handle_category_pagination(callback: types.CallbackQuery, callback_data: CategoryPagination):
    await show_catalog(callback, callback_data.page)
    await callback.answer()


@dp.callback_query(F.data.startswith("show_category_"))
async def show_category_types(callback: types.CallbackQuery):
    category_id = int(callback.data.split("_")[2])
    await show_category_types_page(callback, category_id, 0)
    await callback.answer()


# Показать типы категории с пагинацией
async def show_category_types_page(callback: types.CallbackQuery, category_id: int, page: int = 0):
    chat_id = callback.message.chat.id
    await cleanup_user_messages(chat_id)  # Очищаем предыдущие сообщения

    db = SessionLocal()
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        types = db.query(Type).filter(Type.category_id == category_id).all()

        if not types:
            if not await update_main_menu(chat_id, f"📁 В категории '{category.name}' пока нет типов",
                                          get_start_keyboard()):
                msg = await callback.message.answer(f"📁 В категории '{category.name}' пока нет типов",
                                                    reply_markup=get_start_keyboard())
                main_menu_messages[chat_id] = msg.message_id
            return

        total_types = len(types)
        total_pages = math.ceil(total_types / ITEMS_PER_PAGE)
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_types = types[start_idx:end_idx]

        builder = InlineKeyboardBuilder()
        for type_obj in current_types:
            builder.button(text=type_obj.name, callback_data=f"show_type_{type_obj.id}_0")

        # Кнопки пагинации
        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=TypePagination(category_id=category_id, page=page - 1).pack()
            ))
        if end_idx < total_types:
            pagination_buttons.append(InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=TypePagination(category_id=category_id, page=page + 1).pack()
            ))

        if pagination_buttons:
            builder.row(*pagination_buttons)

        builder.button(text="🔙 Назад", callback_data="catalog")
        builder.adjust(1)

        text = f"🏷️ Типы в категории '{category.name}':\n\nСтраница {page + 1} из {total_pages}"

        if not await update_main_menu(chat_id, text, builder.as_markup()):
            msg = await callback.message.answer(text, reply_markup=builder.as_markup())
            main_menu_messages[chat_id] = msg.message_id

    finally:
        db.close()


# Обработчик пагинации типов
@dp.callback_query(TypePagination.filter())
async def handle_type_pagination(callback: types.CallbackQuery, callback_data: TypePagination):
    await show_category_types_page(callback, callback_data.category_id, callback_data.page)
    await callback.answer()


@dp.callback_query(F.data.startswith("show_type_"))
async def show_type_products(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    type_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    await show_type_products_page(callback, type_id, page)
    await callback.answer()


# Показать товары типа с пагинацией
async def show_type_products_page(callback: types.CallbackQuery, type_id: int, page: int = 0):
    chat_id = callback.message.chat.id
    await cleanup_user_messages(chat_id)  # Очищаем предыдущие сообщения

    db = SessionLocal()
    try:
        type_obj = db.query(Type).filter(Type.id == type_id).first()
        products = db.query(Product).filter(Product.type_id == type_id).all()

        if not products:
            if not await update_main_menu(chat_id, f"🚪 В типе '{type_obj.name}' пока нет товаров",
                                          get_start_keyboard()):
                msg = await callback.message.answer(f"🚪 В типе '{type_obj.name}' пока нет товаров",
                                                    reply_markup=get_start_keyboard())
                main_menu_messages[chat_id] = msg.message_id
            return

        total_products = len(products)
        total_pages = math.ceil(total_products / ITEMS_PER_PAGE)
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_products = products[start_idx:end_idx]

        builder = InlineKeyboardBuilder()
        for product in current_products:
            builder.button(text=product.name, callback_data=f"show_product_{product.id}_{type_id}_{page}")

        # Кнопки пагинации
        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=ProductPagination(type_id=type_id, page=page - 1).pack()
            ))
        if end_idx < total_products:
            pagination_buttons.append(InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=ProductPagination(type_id=type_id, page=page + 1).pack()
            ))

        if pagination_buttons:
            builder.row(*pagination_buttons)

        builder.button(text="🔙 Назад", callback_data=f"show_category_{type_obj.category_id}")
        builder.adjust(1)

        text = f"🚪 Товары в типе '{type_obj.name}':\n\nСтраница {page + 1} из {total_pages}"

        if not await update_main_menu(chat_id, text, builder.as_markup()):
            msg = await callback.message.answer(text, reply_markup=builder.as_markup())
            main_menu_messages[chat_id] = msg.message_id

    finally:
        db.close()


# Обработчик пагинации товаров
@dp.callback_query(ProductPagination.filter())
async def handle_product_pagination(callback: types.CallbackQuery, callback_data: ProductPagination):
    await show_type_products_page(callback, callback_data.type_id, callback_data.page)
    await callback.answer()


# Обработчик возврата к списку товаров
@dp.callback_query(F.data.startswith("back_to_products_"))
async def back_to_products(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    type_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 else 0

    await cleanup_user_messages(callback.message.chat.id)  # Очищаем чат
    await show_type_products_page(callback, type_id, page)
    await callback.answer()


@dp.callback_query(F.data.startswith("show_product_"))
async def show_product_details(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    parts = callback.data.split("_")
    product_id = int(parts[2])
    type_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 else 0

    # Показываем первый медиафайл товара
    await show_product_media(callback, product_id, type_id, page, 0)
    await callback.answer()


# Показать конкретный медиафайл товара с навигацией
async def show_product_media(callback: types.CallbackQuery, product_id: int, type_id: int, page: int, media_index: int):
    chat_id = callback.message.chat.id
    await cleanup_user_messages(chat_id)  # Очищаем предыдущие сообщения

    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product_id).all()

        if not product:
            await callback.answer("❌ Товар не найден")
            return

        if not media_files:
            # Если нет медиафайлов, показываем просто текст с кнопками
            product_text = f"🚪 {product.name}\n\n💰 Цена: {product.price} руб.\n\n📝 {product.description}"

            msg = await bot.send_message(
                chat_id=chat_id,
                text=product_text,
                reply_markup=get_product_keyboard(product.id, product.type_id, page, 0, 0)
            )
            add_user_message(chat_id, msg.message_id)
            return

        # Получаем конкретный медиафайл по индексу
        media_file = media_files[media_index]

        product_text = f"🚪 {product.name}\n\n💰 Цена: {product.price} руб.\n\n📝 {product.description}"

        # Отправляем медиафайл с кнопками навигации
        if media_file.media_type == 'photo':
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=media_file.file_id,
                caption=product_text,
                reply_markup=get_product_keyboard(product.id, type_id, page, media_index, len(media_files))
            )
        else:  # video
            msg = await bot.send_video(
                chat_id=chat_id,
                video=media_file.file_id,
                caption=product_text,
                reply_markup=get_product_keyboard(product.id, type_id, page, media_index, len(media_files))
            )

        add_user_message(chat_id, msg.message_id)

    finally:
        db.close()


# Обработчик навигации по медиа товара
@dp.callback_query(ProductMediaNavigation.filter())
async def handle_product_media_navigation(callback: types.CallbackQuery, callback_data: ProductMediaNavigation):
    await show_product_media(callback, callback_data.product_id, callback_data.type_id, callback_data.page,
                             callback_data.media_index)
    await callback.answer()


# Начало добавления товара в корзину - запрос количества
@dp.callback_query(F.data.startswith("add_to_cart_"))
async def start_add_to_cart(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    parts = callback.data.split("_")
    product_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 else 0

    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            await callback.answer("❌ Товар не найден")
            return

        # Сохраняем информацию о товаре в состоянии
        await state.update_data(
            product_id=product_id,
            product_name=product.name,
            product_price=product.price,
            type_id=product.type_id,
            page=page
        )

        # Запрашиваем количество
        msg = await callback.message.answer(
            f"🚪 {product.name}\n"
            f"💰 Цена: {product.price} руб.\n\n"
            "📝 Введите количество товара:",
            reply_markup=get_cancel_quantity_keyboard(product_id, product.type_id, page)
        )
        add_user_message(chat_id, msg.message_id)

        await state.set_state(CartState.waiting_for_quantity)

    finally:
        db.close()

    await callback.answer()


# Обработчик отмены ввода количества
@dp.callback_query(F.data.startswith("cancel_quantity_"))
async def cancel_quantity(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    parts = callback.data.split("_")
    product_id = int(parts[2])
    type_id = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 else 0

    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            # Возвращаемся к первому медиафайлу товара
            await show_product_media(callback, product_id, type_id, page, 0)
        else:
            await callback.answer("❌ Товар не найден")
    finally:
        db.close()

    await state.clear()
    await callback.answer()


# Обработчик ввода количества товара
@dp.message(CartState.waiting_for_quantity, F.text)
async def process_quantity(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    user_data = await state.get_data()
    product_id = user_data.get('product_id')
    product_name = user_data.get('product_name')
    product_price = user_data.get('product_price')
    type_id = user_data.get('type_id')
    page = user_data.get('page', 0)

    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer("❌ Количество должно быть больше 0! Введите корректное количество:")
            return
        if quantity > 100:
            await message.answer("❌ Слишком большое количество! Введите количество до 100:")
            return

    except ValueError:
        await message.answer("❌ Пожалуйста, введите число! Введите количество товара:")
        return

    user_id = message.from_user.id

    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            await message.answer("❌ Товар не найден")
            await state.clear()
            return

        # Проверяем, есть ли уже такой товар в корзине
        cart_item = db.query(Cart).filter(
            Cart.user_id == user_id,
            Cart.product_id == product_id
        ).first()

        if cart_item:
            cart_item.quantity += quantity
        else:
            cart_item = Cart(user_id=user_id, product_id=product_id, quantity=quantity)
            db.add(cart_item)

        db.commit()

        total_price = product_price * quantity

        # Очищаем предыдущие сообщения и показываем подтверждение
        await cleanup_user_messages(chat_id)

        confirmation_msg = await message.answer(
            f"✅ {product.name} добавлен в корзину!\n"
            f"📦 Количество: {quantity} шт.\n"
            f"💰 Сумма: {total_price} руб.",
            reply_markup=get_after_cart_keyboard(type_id, page)
        )
        add_user_message(chat_id, confirmation_msg.message_id)

    except Exception as e:
        db.rollback()
        await message.answer("❌ Ошибка при добавлении в корзину")
        logger.error(f"Cart error: {e}")
    finally:
        db.close()

    await state.clear()


# Просмотр корзины с отдельными сообщениями для каждого товара
@dp.callback_query(F.data == "view_cart")
async def view_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    await cleanup_user_messages(chat_id)  # Очищаем предыдущие сообщения

    db = SessionLocal()
    try:
        cart_items = db.query(Cart).filter(Cart.user_id == user_id).all()

        if not cart_items:
            await callback.answer("🛒 Ваша корзина пуста")
            return

        total_amount = 0
        items_processed = 0

        # Отправляем каждый товар отдельным сообщением
        for item in cart_items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                item_total = product.price * item.quantity
                total_amount += item_total

                # Получаем медиафайлы товара
                media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product.id).all()

                item_text = (
                    f"🚪 {product.name}\n"
                    f"💰 Цена: {product.price} руб. x {item.quantity} = {item_total} руб.\n"
                    f"📝 {product.description}"
                )

                if media_files:
                    # Отправляем первое фото товара
                    first_media = media_files[0]
                    if first_media.media_type == 'photo':
                        msg = await bot.send_photo(
                            chat_id=chat_id,
                            photo=first_media.file_id,
                            caption=item_text,
                            reply_markup=get_cart_item_keyboard(item.id)
                        )
                    else:
                        msg = await bot.send_video(
                            chat_id=chat_id,
                            video=first_media.file_id,
                            caption=item_text,
                            reply_markup=get_cart_item_keyboard(item.id)
                        )
                else:
                    # Если нет медиа, отправляем просто текст
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=item_text,
                        reply_markup=get_cart_item_keyboard(item.id)
                    )

                add_user_message(chat_id, msg.message_id)
                items_processed += 1

        # Отправляем итоговое сообщение с суммой
        summary_text = f"💰 Общая сумма заказа: {total_amount} руб.\n\n📦 Товаров в корзине: {items_processed}"
        summary_msg = await bot.send_message(
            chat_id=chat_id,
            text=summary_text,
            reply_markup=get_cart_summary_keyboard()
        )
        add_user_message(chat_id, summary_msg.message_id)

    finally:
        db.close()
    await callback.answer()


# Удаление товара из корзины
@dp.callback_query(F.data.startswith("remove_from_cart_"))
async def remove_from_cart(callback: types.CallbackQuery):
    cart_item_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    db = SessionLocal()
    try:
        cart_item = db.query(Cart).filter(Cart.id == cart_item_id).first()
        if cart_item and cart_item.user_id == user_id:
            product_name = cart_item.product.name
            db.delete(cart_item)
            db.commit()

            # Удаляем сообщение с товаром
            try:
                await callback.message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")

            await callback.answer(f"✅ {product_name} удален из корзины")

            # Обновляем вид корзины
            await view_cart(callback)
        else:
            await callback.answer("❌ Товар не найден в корзине")
    except Exception as e:
        db.rollback()
        await callback.answer("❌ Ошибка при удалении товара")
    finally:
        db.close()


# Очистка корзины
@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    db = SessionLocal()
    try:
        cart_items = db.query(Cart).filter(Cart.user_id == user_id).all()
        for item in cart_items:
            db.delete(item)
        db.commit()

        await callback.answer("✅ Корзина очищена")

        # Возвращаемся в меню корзины
        await show_cart_menu(callback)

    except Exception as e:
        db.rollback()
        await callback.answer("❌ Ошибка при очистке корзины")
    finally:
        db.close()


# Оформление заказа
@dp.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    db = SessionLocal()
    try:
        cart_items = db.query(Cart).filter(Cart.user_id == user_id).all()

        if not cart_items:
            await callback.answer("❌ Корзина пуста")
            return

        # Сохраняем информацию о корзине в состоянии
        cart_data = []
        total_amount = 0

        for item in cart_items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                item_total = product.price * item.quantity
                total_amount += item_total
                cart_data.append({
                    'cart_item_id': item.id,
                    'product_id': product.id,
                    'product_name': product.name,
                    'price': product.price,
                    'quantity': item.quantity,
                    'total': item_total,
                    'description': product.description
                })

        await state.update_data(cart_data=cart_data, total_amount=total_amount)

        await callback.message.answer(
            "📞 Для оформления заказа, пожалуйста, отправьте ваш номер телефона для связи.\n\n"
            "Вы можете отправить номер в любом формате:",
        )
        await state.set_state(OrderState.waiting_for_phone)

    finally:
        db.close()
    await callback.answer()


@dp.message(OrderState.waiting_for_phone, F.text)
async def process_order(message: types.Message, state: FSMContext):
    phone_number = message.text.strip()
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    chat_id = message.chat.id

    db = SessionLocal()
    try:
        user_data = await state.get_data()
        cart_data = user_data.get('cart_data', [])
        total_amount = user_data.get('total_amount', 0)

        if not cart_data:
            await message.answer("❌ Корзина пуста")
            await state.clear()
            return

        # Создаем заказ
        new_order = Order(
            user_id=user_id,
            user_name=user_name,
            phone_number=phone_number,
            total_amount=total_amount,
            created_at=datetime.now().strftime("%d.%m.%Y %H:%M")
        )
        db.add(new_order)
        db.flush()  # Получаем ID заказа

        # Добавляем товары заказа
        order_items_info = []
        for item_data in cart_data:
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=item_data['product_id'],
                product_name=item_data['product_name'],
                product_price=item_data['price'],
                quantity=item_data['quantity']
            )
            db.add(order_item)
            order_items_info.append(item_data)

        # Очищаем корзину
        cart_items = db.query(Cart).filter(Cart.user_id == user_id).all()
        for item in cart_items:
            db.delete(item)

        db.commit()

        # Формируем сообщение для админа с медиа
        admin_text = (
            f"📦 Новый заказ #{new_order.id}\n\n"
            f"👤 Пользователь: {user_name} (ID: {user_id})\n"
            f"📞 Телефон: {phone_number}\n"
            f"💰 Общая сумма: {total_amount} руб.\n\n"
            f"🛒 Состав заказа:\n"
        )

        for item_info in order_items_info:
            admin_text += f"• {item_info['product_name']} - {item_info['price']} руб. x {item_info['quantity']}\n"

        # Отправляем админу сначала текстовое сообщение
        # Отправляем всем админам сначала текстовое сообщение
        for admin_id in ADMIN_IDS:  # Было ADMIN_ID, стало ADMIN_IDS
            await bot.send_message(admin_id, admin_text)

        # Затем отправляем всем админам фотографии товаров из заказа
        for item_info in order_items_info:
            product_id = item_info['product_id']
            media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product_id).all()

            if media_files:
                first_media = media_files[0]
                item_caption = (
                    f"🚪 {item_info['product_name']}\n"
                    f"💰 {item_info['price']} руб. x {item_info['quantity']} = {item_info['total']} руб.\n"
                    f"📞 Телефон заказчика: {phone_number}\n"
                    f"👤 Имя: {user_name}"
                )

                for admin_id in ADMIN_IDS:  # Было ADMIN_ID, стало ADMIN_IDS
                    if first_media.media_type == 'photo':
                        await bot.send_photo(
                            chat_id=admin_id,
                            photo=first_media.file_id,
                            caption=item_caption
                        )
                    else:
                        await bot.send_video(
                            chat_id=admin_id,
                            video=first_media.file_id,
                            caption=item_caption
                        )

        # Подтверждаем пользователю
        await message.answer(
            f"✅ Ваш заказ #{new_order.id} принят!\n\n"
            f"💰 Сумма заказа: {total_amount} руб.\n"
            f"📞 Мы свяжемся с вами по номеру: {phone_number}\n\n"
            "Спасибо за покупку! 🚪"
        )

        # Возвращаемся в главное меню
        await update_main_menu(chat_id,
                               "Добро пожаловать в магазин дверей! 🚪\n\nВыберите нужный раздел:",
                               get_start_keyboard()
                               )

    except Exception as e:
        db.rollback()
        await message.answer("❌ Ошибка при оформлении заказа")
        logger.error(f"Order error: {e}")
    finally:
        db.close()

    await state.clear()


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id

    await cleanup_user_messages(chat_id)  # Очищаем все сообщения

    welcome_text = (
        "Добро пожаловать в магазин дверей! 🚪\n\n"
        "Выберите нужный раздел:"
    )

    await update_main_menu(
        chat_id,
        welcome_text,
        get_start_keyboard()
    )
    await callback.answer()


# Запуск бота
async def main():
    # Создаем таблицы в БД и выполняем миграцию
    print("Инициализация базы данных...")
    create_tables()
    print("База данных готова")

    # Даем время на завершение миграции
    await asyncio.sleep(1)

    print("Запуск бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())