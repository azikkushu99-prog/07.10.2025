from aiogram import Bot, types, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ContentType
from aiogram.utils.keyboard import InlineKeyboardBuilder
import os
import logging
from typing import List
from functools import wraps
from datetime import datetime

from db import Category, Type, Product, ProductMedia, SessionLocal, Order, OrderItem, MainMenuSection
from config import ADMIN_IDS, MEDIA_FOLDER  # Изменено на ADMIN_IDS

# Setup logging for admin module
logger = logging.getLogger(__name__)

admin_router = Router()


# Декоратор для проверки админа
def admin_required(handler):
    @wraps(handler)
    async def wrapper(*args, **kwargs):
        message = None
        for arg in args:
            if isinstance(arg, (types.Message, types.CallbackQuery)):
                message = arg
                break
        if not message:
            message = kwargs.get('message') or kwargs.get('callback_query') or kwargs.get('event')

        # Изменено: проверка на вхождение в список ADMIN_IDS
        if message and hasattr(message, 'from_user') and message.from_user.id not in ADMIN_IDS:
            if hasattr(message, 'answer'):
                await message.answer("⛔ У вас нет прав для выполнения этой команды.")
            elif hasattr(message, 'message') and hasattr(message.message, 'answer'):
                await message.message.answer("⛔ У вас нет прав для выполнения этой команды.")
            return

        return await handler(*args, **kwargs)

    return wrapper



# Состояния для FSM
class AddCategory(StatesGroup):
    entering_name = State()


class AddType(StatesGroup):
    choosing_category = State()
    entering_name = State()


class AddProduct(StatesGroup):
    choosing_category = State()
    choosing_type = State()
    entering_name = State()
    entering_description = State()
    entering_price = State()
    adding_media = State()


class DeleteCategory(StatesGroup):
    choosing_category = State()


class DeleteType(StatesGroup):
    choosing_category = State()
    choosing_type = State()


class DeleteProduct(StatesGroup):
    choosing_category = State()
    choosing_type = State()
    choosing_product = State()


# Состояния для редактирования главного меню
class EditMainMenu(StatesGroup):
    choosing_section = State()
    editing_text = State()
    editing_photo = State()


# Клавиатура админ-панели
def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Добавить категорию", callback_data="add_category"),
            InlineKeyboardButton(text="➖ Удалить категорию", callback_data="delete_category")
        ],
        [
            InlineKeyboardButton(text="🏷️ Добавить тип", callback_data="add_type"),
            InlineKeyboardButton(text="🗑️ Удалить тип", callback_data="delete_type")
        ],
        [
            InlineKeyboardButton(text="🚪 Добавить товар", callback_data="add_product"),
            InlineKeyboardButton(text="❌ Удалить товар", callback_data="delete_product")
        ],
        [
            InlineKeyboardButton(text="📦 Заказы", callback_data="view_orders"),
            InlineKeyboardButton(text="📝 Редактировать информацию", callback_data="edit_main_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# Команда /admin
@admin_router.message(Command("admin"))
@admin_required
async def cmd_admin(message: Message):
    await message.answer(
        "👨‍💻 Панель администратора\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )


# Обработчики кнопок админ-панели
@admin_router.callback_query(F.data == "admin_panel")
@admin_required
async def back_to_admin_panel(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👨‍💻 Панель администратора\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )


# Просмотр заказов с улучшенным отображением
@admin_router.callback_query(F.data == "view_orders")
@admin_required
async def view_orders(callback: types.CallbackQuery):
    db = SessionLocal()
    try:
        # Показываем только активных заказы
        orders = db.query(Order).filter(Order.status == "pending").order_by(Order.id.desc()).all()
        if not orders:
            await callback.message.answer("📦 Нет активных заказов")
            await callback.answer()
            return

        for order in orders:
            order_items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            order_text = (
                f"📦 Заказ #{order.id}\n"
                f"👤 Пользователь: {order.user_name}\n"
                f"📞 Телефон: {order.phone_number}\n"
                f"💰 Сумма: {order.total_amount} руб.\n"
                f"📅 Дата: {order.created_at}\n"
                f"🛒 Товары:\n"
            )

            # Добавляем информацию о товарах с первыми фотографиями
            for item in order_items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product.id).all()
                    if media_files:
                        first_media = media_files[0]
                        # Отправляем фото товара
                        if first_media.media_type == 'photo':
                            await callback.message.answer_photo(
                                photo=first_media.file_id,
                                caption=(
                                    f"🚪 {product.name}\n"
                                    f"📦 Заказ #{order.id}\n"
                                    f"👤 {order.user_name}\n"
                                    f"📞 {order.phone_number}\n"
                                    f"💰 {item.product_price} руб. x {item.quantity} = {item.product_price * item.quantity} руб."
                                )
                            )
                        else:
                            await callback.message.answer_video(
                                video=first_media.file_id,
                                caption=(
                                    f"🚪 {product.name}\n"
                                    f"📦 Заказ #{order.id}\n"
                                    f"👤 {order.user_name}\n"
                                    f"📞 {order.phone_number}\n"
                                    f"💰 {item.product_price} руб. x {item.quantity} = {item.product_price * item.quantity} руб."
                                )
                            )

            # Формируем текст заказа
            for item in order_items:
                order_text += f"• {item.product_name} - {item.product_price} руб. x {item.quantity}\n"

            # Только кнопка "Выполнен"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Выполнен", callback_data=f"complete_order_{order.id}")]
            ])
            await callback.message.answer(order_text, reply_markup=keyboard)

        await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())

    finally:
        db.close()
    await callback.answer()


# Обработчик выполнения заказа
@admin_router.callback_query(F.data.startswith("complete_order_"))
@admin_required
async def complete_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.status = "completed"
            db.commit()

            # Удаляем сообщение с заказом
            try:
                await callback.message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")

            await callback.answer(f"✅ Заказ #{order_id} выполнен и удален из списка")
        else:
            await callback.answer("❌ Заказ не найден")
    except Exception as e:
        db.rollback()
        await callback.answer("❌ Ошибка при выполнении заказа")
        logger.error(f"Order completion error: {e}")
    finally:
        db.close()


# Начало редактирования главного меню
@admin_router.callback_query(F.data == "edit_main_menu")
@admin_required
async def start_edit_main_menu(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠️ Услуги", callback_data="edit_section_services")],
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="edit_section_info")],
        [InlineKeyboardButton(text="💬 Консультация", callback_data="edit_section_consultation")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

    await callback.message.edit_text(
        "📝 Редактирование главного меню\n\nКакую информацию хотите изменить?",
        reply_markup=keyboard
    )
    await state.set_state(EditMainMenu.choosing_section)
    await callback.answer()


# Обработчик выбора раздела для редактирования - ИСПРАВЛЕННЫЙ ФИЛЬТР
@admin_router.callback_query(EditMainMenu.choosing_section, F.data.startswith("edit_section_"))
@admin_required
async def choose_section_to_edit(callback: types.CallbackQuery, state: FSMContext):
    section_key = callback.data.replace("edit_section_", "")  # services, info, consultation

    db = SessionLocal()
    try:
        section = db.query(MainMenuSection).filter(MainMenuSection.section_key == section_key).first()
        if not section:
            await callback.answer("❌ Раздел не найден в базе данных")
            return

        await state.update_data(section_key=section_key, section_id=section.id)

        # Показываем текущее содержимое раздела
        current_content = f"📝 Редактирование раздела: {section.title}\n\n"
        current_content += f"Текущий текст:\n{section.content}\n\n"
        current_content += "Введите новый текст для этого раздела:"

        await callback.message.edit_text(current_content)
        await state.set_state(EditMainMenu.editing_text)

    except Exception as e:
        logger.error(f"Error in choose_section_to_edit: {e}")
        await callback.answer("❌ Ошибка при загрузке раздела")
    finally:
        db.close()


# Обработчик ввода нового текста
@admin_router.message(EditMainMenu.editing_text, F.text)
@admin_required
async def process_section_text(message: Message, state: FSMContext):
    new_text = message.text
    user_data = await state.get_data()
    section_key = user_data['section_key']
    section_id = user_data['section_id']

    db = SessionLocal()
    try:
        section = db.query(MainMenuSection).filter(MainMenuSection.id == section_id).first()
        if section:
            section.content = new_text
            db.commit()

            # Предлагаем изменить фото
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🖼️ Изменить фото", callback_data="change_photo")],
                [InlineKeyboardButton(text="🗑️ Удалить текущее фото", callback_data="remove_photo")],
                [InlineKeyboardButton(text="➡️ Пропустить", callback_data="skip_photo")]
            ])

            photo_status = "есть" if section.photo_path else "нет"
            await message.answer(
                f"✅ Текст раздела обновлен!\n\n"
                f"Текущее фото: {photo_status}\n"
                f"Выберите действие с фото:",
                reply_markup=keyboard
            )
            await state.set_state(EditMainMenu.editing_photo)
        else:
            await message.answer("❌ Раздел не найден")
            await state.clear()

    except Exception as e:
        db.rollback()
        await message.answer("❌ Ошибка при обновлении текста")
        logger.error(f"Section text update error: {e}")
        await state.clear()
    finally:
        db.close()


# Обработчик действий с фото
@admin_router.callback_query(EditMainMenu.editing_photo, F.data.in_(["change_photo", "remove_photo", "skip_photo"]))
@admin_required
async def handle_photo_action(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    action = callback.data
    user_data = await state.get_data()
    section_id = user_data['section_id']

    db = SessionLocal()
    try:
        section = db.query(MainMenuSection).filter(MainMenuSection.id == section_id).first()
        if not section:
            await callback.answer("❌ Раздел не найден")
            await state.clear()
            return

        if action == "remove_photo":
            # Удаляем текущее фото
            if section.photo_path and os.path.exists(section.photo_path):
                try:
                    os.remove(section.photo_path)
                except Exception as e:
                    logger.error(f"Ошибка при удалении файла {section.photo_path}: {e}")

            section.photo_path = None
            section.file_id = None
            db.commit()

            await callback.message.answer("✅ Фото удалено! Раздел главного меню обновлен.")
            await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())
            await state.clear()

        elif action == "change_photo":
            await callback.message.answer("🖼️ Отправьте новое фото для этого раздела:")
            # Состояние уже установлено в editing_photo, ждем фото

        elif action == "skip_photo":
            await callback.message.answer("✅ Раздел главного меню обновлен!")
            await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())
            await state.clear()

    except Exception as e:
        db.rollback()
        await callback.message.answer("❌ Ошибка при обработке фото")
        logger.error(f"Photo action error: {e}")
        await state.clear()
    finally:
        db.close()

    await callback.answer()


# Обработчик загрузки нового фото
@admin_router.message(EditMainMenu.editing_photo, F.content_type == ContentType.PHOTO)
@admin_required
async def process_section_photo(message: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    section_id = user_data['section_id']

    db = SessionLocal()
    try:
        section = db.query(MainMenuSection).filter(MainMenuSection.id == section_id).first()
        if not section:
            await message.answer("❌ Раздел не найден")
            await state.clear()
            return

        # Удаляем старое фото, если оно есть
        if section.photo_path and os.path.exists(section.photo_path):
            try:
                os.remove(section.photo_path)
            except Exception as e:
                logger.error(f"Ошибка при удалении старого файла {section.photo_path}: {e}")

        # Сохраняем новое фото
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        file_path = f"files/{file_id}_{message.message_id}.jpg"
        await bot.download_file(file.file_path, file_path)

        # Обновляем запись в БД
        section.photo_path = file_path
        section.file_id = file_id
        db.commit()

        await message.answer("✅ Фото обновлено! Раздел главного меню полностью обновлен.")
        await message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())

    except Exception as e:
        db.rollback()
        await message.answer("❌ Ошибка при загрузке фото")
        logger.error(f"Photo upload error: {e}")
    finally:
        db.close()

    await state.clear()


# Обработчики для остальных функций админ-панели (добавление/удаление категорий, типов, товаров)
# ... [здесь остаются все ваши существующие обработчики для товаров, категорий и типов]

# Добавление категории
@admin_router.callback_query(F.data == "add_category")
@admin_required
async def start_add_category(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Введите название новой категории:")
    await state.set_state(AddCategory.entering_name)
    await callback.answer()


@admin_router.message(AddCategory.entering_name, F.text)
@admin_required
async def process_category_name(message: Message, state: FSMContext):
    category_name = message.text.strip()
    db = SessionLocal()
    try:
        existing_category = db.query(Category).filter(Category.name == category_name).first()
        if existing_category:
            await message.answer("❌ Категория с таким названием уже существует!")
            return

        new_category = Category(name=category_name)
        db.add(new_category)
        db.commit()
        await message.answer(f"✅ Категория '{category_name}' успешно добавлена!")
        await message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())
    except Exception as e:
        db.rollback()
        await message.answer("❌ Ошибка при добавлении категории!")
    finally:
        db.close()
    await state.clear()


# Добавление типа
@admin_router.callback_query(F.data == "add_type")
@admin_required
async def start_add_type(callback: types.CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        if not categories:
            await callback.message.answer("❌ Сначала создайте хотя бы одну категорию!")
            await callback.answer()
            return

        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.button(text=category.name, callback_data=f"cat_{category.id}")
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        builder.adjust(1)

        await callback.message.answer(
            "📁 Выберите категорию для нового типа:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(AddType.choosing_category)
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(AddType.choosing_category, F.data.startswith("cat_"))
@admin_required
async def process_category_for_type(callback: types.CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[1])
    await state.update_data(category_id=category_id)
    await callback.message.answer("🏷️ Введите название нового типа:")
    await state.set_state(AddType.entering_name)
    await callback.answer()


@admin_router.message(AddType.entering_name, F.text)
@admin_required
async def process_type_name(message: Message, state: FSMContext):
    type_name = message.text.strip()
    user_data = await state.get_data()
    category_id = user_data['category_id']
    db = SessionLocal()
    try:
        existing_type = db.query(Type).filter(
            Type.name == type_name,
            Type.category_id == category_id
        ).first()
        if existing_type:
            await message.answer("❌ Тип с таким названием уже существует в этой категории!")
            return

        new_type = Type(name=type_name, category_id=category_id)
        db.add(new_type)
        db.commit()
        category = db.query(Category).filter(Category.id == category_id).first()
        await message.answer(f"✅ Тип '{type_name}' успешно добавлен в категорию '{category.name}'!")
        await message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())
    except Exception as e:
        db.rollback()
        await message.answer("❌ Ошибка при добавлении типа!")
    finally:
        db.close()
    await state.clear()


# Добавление товара
@admin_router.callback_query(F.data == "add_product")
@admin_required
async def start_add_product(callback: types.CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        if not categories:
            await callback.message.answer("❌ Сначала создайте хотя бы одну категорию!")
            await callback.answer()
            return

        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.button(text=category.name, callback_data=f"product_cat_{category.id}")
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        builder.adjust(1)

        await callback.message.answer(
            "📁 Выберите категорию для товара:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(AddProduct.choosing_category)
        await state.update_data(media_files=[])
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(AddProduct.choosing_category, F.data.startswith("product_cat_"))
@admin_required
async def process_product_category(callback: types.CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[2])
    await state.update_data(category_id=category_id)
    db = SessionLocal()
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        types = db.query(Type).filter(Type.category_id == category_id).all()
        if not types:
            await callback.message.answer(f"❌ В категории '{category.name}' нет типов! Сначала создайте тип.")
            await state.clear()
            return

        builder = InlineKeyboardBuilder()
        for type_obj in types:
            builder.button(text=type_obj.name, callback_data=f"product_type_{type_obj.id}")
        builder.button(text="🔙 Назад", callback_data="add_product")
        builder.adjust(1)

        await callback.message.answer(
            f"🏷️ Выберите тип в категории '{category.name}':",
            reply_markup=builder.as_markup()
        )
        await state.set_state(AddProduct.choosing_type)
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(AddProduct.choosing_type, F.data.startswith("product_type_"))
@admin_required
async def process_product_type(callback: types.CallbackQuery, state: FSMContext):
    type_id = int(callback.data.split("_")[2])
    await state.update_data(type_id=type_id)
    await callback.message.answer("🚪 Введите название товара:")
    await state.set_state(AddProduct.entering_name)
    await callback.answer()


@admin_router.message(AddProduct.entering_name, F.text)
@admin_required
async def process_product_name(message: Message, state: FSMContext):
    product_name = message.text.strip()
    await state.update_data(product_name=product_name)
    await message.answer("📝 Введите описание товара:")
    await state.set_state(AddProduct.entering_description)


@admin_router.message(AddProduct.entering_description, F.text)
@admin_required
async def process_product_description(message: Message, state: FSMContext):
    product_description = message.text.strip()
    await state.update_data(product_description=product_description)
    await message.answer("💰 Введите цену товара в рублях (только число):")
    await state.set_state(AddProduct.entering_price)


@admin_router.message(AddProduct.entering_price, F.text)
@admin_required
async def process_product_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price <= 0:
            await message.answer("❌ Цена должна быть положительным числом!")
            return
        await state.update_data(price=price)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить добавление медиа", callback_data="finish_media")]
        ])
        await message.answer(
            "🖼️ Теперь отправьте фото или видео товара.\nМожно отправить несколько файлов.\nКогда закончите, нажмите кнопку ниже:",
            reply_markup=keyboard
        )
        await state.set_state(AddProduct.adding_media)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную цену (только число):")


@admin_router.message(AddProduct.adding_media, F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO}))
@admin_required
async def process_product_media(message: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    media_files = user_data.get('media_files', [])
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            media_type = "video"
        else:
            await message.answer("❌ Поддерживаются только фото и видео!")
            return

        file = await bot.get_file(file_id)
        file_path = f"{MEDIA_FOLDER}/{file_id}_{message.message_id}.jpg" if media_type == "photo" else f"{MEDIA_FOLDER}/{file_id}_{message.message_id}.mp4"
        await bot.download_file(file.file_path, file_path)

        media_files.append({
            'file_id': file_id,
            'file_path': file_path,
            'media_type': media_type
        })
        await state.update_data(media_files=media_files)
        await message.answer(f"✅ Медиафайл добавлен! Всего файлов: {len(media_files)}")
    except Exception as e:
        await message.answer("❌ Ошибка при обработке медиафайла!")


@admin_router.callback_query(AddProduct.adding_media, F.data == "finish_media")
@admin_required
async def finish_media_and_save_product(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    if not user_data.get('media_files'):
        await callback.message.answer("❌ Вы не добавили ни одного медиафайла! Добавьте хотя бы один.")
        await callback.answer()
        return

    db = SessionLocal()
    try:
        new_product = Product(
            name=user_data['product_name'],
            description=user_data['product_description'],
            price=user_data['price'],
            type_id=user_data['type_id']
        )
        db.add(new_product)
        db.flush()

        for media_info in user_data['media_files']:
            media = ProductMedia(
                product_id=new_product.id,
                file_id=media_info['file_id'],
                file_path=media_info['file_path'],
                media_type=media_info['media_type']
            )
            db.add(media)

        db.commit()
        product_type = db.query(Type).filter(Type.id == user_data['type_id']).first()
        category = db.query(Category).filter(Category.id == user_data['category_id']).first()

        success_message = (
            f"✅ Товар успешно добавлен!\n\n"
            f"📁 Категория: {category.name}\n"
            f"🏷️ Тип: {product_type.name}\n"
            f"🚪 Товар: {user_data['product_name']}\n"
            f"💰 Цена: {user_data['price']} руб.\n"
            f"📝 Описание: {user_data['product_description']}\n"
            f"🖼️ Медиафайлов: {len(user_data['media_files'])}"
        )

        await callback.message.answer(success_message)
        await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())
    except Exception as e:
        db.rollback()
        await callback.message.answer("❌ Ошибка при сохранении товара!")
    finally:
        db.close()
    await state.clear()
    await callback.answer()


# Удаление категории
@admin_router.callback_query(F.data == "delete_category")
@admin_required
async def start_delete_category(callback: types.CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        if not categories:
            await callback.message.answer("❌ Нет категорий для удаления!")
            await callback.answer()
            return

        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.button(text=category.name, callback_data=f"confirm_delete_category_{category.id}")
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        builder.adjust(1)

        await callback.message.answer(
            "📁 Выберите категорию для удаления:",
            reply_markup=builder.as_markup()
        )
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(F.data.startswith("confirm_delete_category_"))
@admin_required
async def process_delete_category(callback: types.CallbackQuery):
    category_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            await callback.message.answer("❌ Категория не найдена!")
            await callback.answer()
            return

        # Получаем все типы в категории
        types = db.query(Type).filter(Type.category_id == category_id).all()
        deleted_files_count = 0

        # Удаляем все товары и медиафайлы в этих типах
        for type_obj in types:
            products = db.query(Product).filter(Product.type_id == type_obj.id).all()
            for product in products:
                # Удаляем медиафайлы товара и физические файлы
                media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product.id).all()
                for media in media_files:
                    # Удаляем файл с диска
                    if os.path.exists(media.file_path):
                        try:
                            os.remove(media.file_path)
                            deleted_files_count += 1
                        except Exception as e:
                            logger.error(f"Ошибка при удалении файла {media.file_path}: {e}")
                    db.delete(media)
                db.delete(product)
            db.delete(type_obj)

        # Удаляем саму категорию
        category_name = category.name
        db.delete(category)
        db.commit()

        await callback.message.answer(
            f"✅ Категория '{category_name}' и все связанные типы и товары удалены!\n"
            f"🗑️ Удалено медиафайлов: {deleted_files_count}"
        )
        await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())

    except Exception as e:
        db.rollback()
        await callback.message.answer("❌ Ошибка при удалении категории!")
    finally:
        db.close()
    await callback.answer()


# Удаление типа
@admin_router.callback_query(F.data == "delete_type")
@admin_required
async def start_delete_type(callback: types.CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        if not categories:
            await callback.message.answer("❌ Нет категорий для удаления типов!")
            await callback.answer()
            return

        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.button(text=category.name, callback_data=f"delete_type_category_{category.id}")
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        builder.adjust(1)

        await callback.message.answer(
            "📁 Выберите категорию:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(DeleteType.choosing_category)
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(DeleteType.choosing_category, F.data.startswith("delete_type_category_"))
@admin_required
async def choose_type_for_deletion(callback: types.CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        types = db.query(Type).filter(Type.category_id == category_id).all()
        if not types:
            await callback.message.answer(f"❌ В категории '{category.name}' нет типов!")
            await state.clear()
            return

        builder = InlineKeyboardBuilder()
        for type_obj in types:
            builder.button(text=type_obj.name, callback_data=f"confirm_delete_type_{type_obj.id}")
        builder.button(text="🔙 Назад", callback_data="delete_type")
        builder.adjust(1)

        await callback.message.answer(
            f"🏷️ Выберите тип для удаления из категории '{category.name}':",
            reply_markup=builder.as_markup()
        )
        await state.set_state(DeleteType.choosing_type)
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(DeleteType.choosing_type, F.data.startswith("confirm_delete_type_"))
@admin_required
async def process_delete_type(callback: types.CallbackQuery, state: FSMContext):
    type_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    try:
        type_obj = db.query(Type).filter(Type.id == type_id).first()
        if not type_obj:
            await callback.message.answer("❌ Тип не найден!")
            await callback.answer()
            return

        # Удаляем все товары и медиафайлы в этом типе
        products = db.query(Product).filter(Product.type_id == type_id).all()
        deleted_files_count = 0

        for product in products:
            # Удаляем медиафайлы товара
            media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product.id).all()
            for media in media_files:
                # Удаляем файл с диска
                if os.path.exists(media.file_path):
                    try:
                        os.remove(media.file_path)
                        deleted_files_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка при удалении файла {media.file_path}: {e}")
                db.delete(media)
            db.delete(product)

        # Удаляем сам тип
        type_name = type_obj.name
        db.delete(type_obj)
        db.commit()

        await callback.message.answer(
            f"✅ Тип '{type_name}' и все связанные товары удалены!\n"
            f"🗑️ Удалено медиафайлов: {deleted_files_count}"
        )
        await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())

    except Exception as e:
        db.rollback()
        await callback.message.answer("❌ Ошибка при удалении типа!")
    finally:
        db.close()
    await state.clear()
    await callback.answer()


# Удаление товара
@admin_router.callback_query(F.data == "delete_product")
@admin_required
async def start_delete_product(callback: types.CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        if not categories:
            await callback.message.answer("❌ Нет категорий для удаления товаров!")
            await callback.answer()
            return

        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.button(text=category.name, callback_data=f"delete_product_category_{category.id}")
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        builder.adjust(1)

        await callback.message.answer(
            "📁 Выберите категорию:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(DeleteProduct.choosing_category)
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(DeleteProduct.choosing_category, F.data.startswith("delete_product_category_"))
@admin_required
async def choose_type_for_product_deletion(callback: types.CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[3])
    await state.update_data(category_id=category_id)
    db = SessionLocal()
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        types = db.query(Type).filter(Type.category_id == category_id).all()
        if not types:
            await callback.message.answer(f"❌ В категории '{category.name}' нет типов!")
            await state.clear()
            return

        builder = InlineKeyboardBuilder()
        for type_obj in types:
            builder.button(text=type_obj.name, callback_data=f"delete_product_type_{type_obj.id}")
        builder.button(text="🔙 Назад", callback_data="delete_product")
        builder.adjust(1)

        await callback.message.answer(
            f"🏷️ Выберите тип из категории '{category.name}':",
            reply_markup=builder.as_markup()
        )
        await state.set_state(DeleteProduct.choosing_type)
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(DeleteProduct.choosing_type, F.data.startswith("delete_product_type_"))
@admin_required
async def choose_product_for_deletion(callback: types.CallbackQuery, state: FSMContext):
    type_id = int(callback.data.split("_")[3])
    await state.update_data(type_id=type_id)
    db = SessionLocal()
    try:
        type_obj = db.query(Type).filter(Type.id == type_id).first()
        products = db.query(Product).filter(Product.type_id == type_id).all()
        if not products:
            await callback.message.answer(f"❌ В типе '{type_obj.name}' нет товаров!")
            await state.clear()
            return

        builder = InlineKeyboardBuilder()
        for product in products:
            builder.button(text=product.name, callback_data=f"confirm_delete_product_{product.id}")
        builder.button(text="🔙 Назад", callback_data=f"delete_product_category_{type_obj.category_id}")
        builder.adjust(1)

        await callback.message.answer(
            f"🚪 Выберите товар для удаления из типа '{type_obj.name}':",
            reply_markup=builder.as_markup()
        )
    finally:
        db.close()
    await callback.answer()


@admin_router.callback_query(F.data.startswith("confirm_delete_product_"))
@admin_required
async def process_delete_product(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            await callback.message.answer("❌ Товар не найден!")
            await callback.answer()
            return

        # Удаляем медиафайлы товара
        media_files = db.query(ProductMedia).filter(ProductMedia.product_id == product_id).all()
        deleted_files_count = 0

        for media in media_files:
            # Удаляем файл с диска
            if os.path.exists(media.file_path):
                try:
                    os.remove(media.file_path)
                    deleted_files_count += 1
                except Exception as e:
                    logger.error(f"Ошибка при удалении файла {media.file_path}: {e}")
            db.delete(media)

        # Удаляем сам товар
        product_name = product.name
        db.delete(product)
        db.commit()

        await callback.message.answer(
            f"✅ Товар '{product_name}' и все связанные медиафайлы удалены!\n"
            f"🗑️ Удалено медиафайлов: {deleted_files_count}"
        )
        await callback.message.answer("👨‍💻 Панель администратора", reply_markup=get_admin_keyboard())

    except Exception as e:
        db.rollback()
        await callback.message.answer("❌ Ошибка при удалении товара!")
    finally:
        db.close()
    await callback.answer()