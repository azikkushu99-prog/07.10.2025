from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from aiogram.filters.callback_data import CallbackData
import os

from config import DATABASE_URL


class CategoryPagination(CallbackData, prefix="cat_pag"):
    page: int


class TypePagination(CallbackData, prefix="type_pag"):
    category_id: int
    page: int


class ProductPagination(CallbackData, prefix="prod_pag"):
    type_id: int
    page: int


# Создаем папки для медиа, если их нет
os.makedirs("doors", exist_ok=True)
os.makedirs("files", exist_ok=True)  # Новая папка для файлов главного меню

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)

    # Связь с типами
    types = relationship("Type", back_populates="category", cascade="all, delete-orphan")


class Type(Base):
    __tablename__ = "types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))

    # Связи
    category = relationship("Category", back_populates="types")
    products = relationship("Product", back_populates="type", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    price = Column(Integer, nullable=False, default=0)  # Цена в рублях с значением по умолчанию
    type_id = Column(Integer, ForeignKey("types.id"))

    # Связи
    type = relationship("Type", back_populates="products")
    media = relationship("ProductMedia", back_populates="product", cascade="all, delete-orphan")


class ProductMedia(Base):
    __tablename__ = "product_media"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    file_id = Column(String(255))  # file_id от Telegram
    file_path = Column(String(500))  # локальный путь к файлу
    media_type = Column(String(10))  # 'photo' или 'video'

    product = relationship("Product", back_populates="media")


# Таблица для корзины пользователей
class Cart(Base):
    __tablename__ = "carts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, default=1)

    product = relationship("Product")


# Таблица для заказов
class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    user_name = Column(String(100))
    phone_number = Column(String(20))
    total_amount = Column(Integer)
    status = Column(String(20), default="pending")
    created_at = Column(String(50))


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    product_name = Column(String(200))
    product_price = Column(Integer)
    quantity = Column(Integer)

    product = relationship("Product")
    order = relationship("Order")


# Новая таблица для разделов главного меню
class MainMenuSection(Base):
    __tablename__ = "main_menu_sections"

    id = Column(Integer, primary_key=True, index=True)
    section_key = Column(String(50), unique=True, nullable=False)  # services, info, consultation
    title = Column(String(100), nullable=False)  # Название раздела
    content = Column(Text, default="")  # Содержимое раздела
    photo_path = Column(String(500), nullable=True)  # Путь к фото
    file_id = Column(String(255), nullable=True)  # file_id от Telegram


# Создаем таблицы
def create_tables():
    Base.metadata.create_all(bind=engine)
    # Запускаем миграцию после создания таблиц
    migrate_database()


def migrate_database():
    """Добавляем отсутствующие столбцы и таблицы в существующую базу данных"""
    db = SessionLocal()
    try:
        # Проверяем существование столбца price в таблице products
        result = db.execute(text("PRAGMA table_info(products)"))
        columns = [row[1] for row in result]

        if 'price' not in columns:
            print("Добавляем столбец price в таблицу products...")
            db.execute(text("ALTER TABLE products ADD COLUMN price INTEGER NOT NULL DEFAULT 0"))
            print("Столбец price успешно добавлен")

        # Проверяем существование таблицы main_menu_sections
        result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='main_menu_sections'"))
        table_exists = result.fetchone()

        if not table_exists:
            print("Создаем таблицу main_menu_sections...")
            MainMenuSection.__table__.create(engine)
            print("Таблица main_menu_sections успешно создана")

        # Проверяем и создаем начальные записи для разделов главного меню
        create_initial_sections(db)
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"Ошибка при миграции базы данных: {e}")
    finally:
        db.close()


def create_initial_sections(db):
    """Создает начальные записи для разделов главного меню"""
    sections_data = [
        {
            'section_key': 'services',
            'title': '🛠️ Услуги',
            'content': '🛠️ Раздел "Услуги" в разработке'
        },
        {
            'section_key': 'info',
            'title': 'ℹ️ Информация',
            'content': 'ℹ️ Раздел "Информация" в разработке'
        },
        {
            'section_key': 'consultation',
            'title': '💬 Консультация',
            'content': '💬 Раздел "Консультация" в разработке'
        }
    ]

    for section_data in sections_data:
        # Проверяем, существует ли уже раздел
        existing_section = db.query(MainMenuSection).filter(
            MainMenuSection.section_key == section_data['section_key']
        ).first()

        if not existing_section:
            print(f"Создаем раздел: {section_data['section_key']}")
            new_section = MainMenuSection(
                section_key=section_data['section_key'],
                title=section_data['title'],
                content=section_data['content']
            )
            db.add(new_section)
        else:
            print(f"Раздел {section_data['section_key']} уже существует")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()