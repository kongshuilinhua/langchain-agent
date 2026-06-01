from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类（Declarative Base）。

    🎯 意图与工程大局观：
        本类作为全平台所有关系型数据库模型（ORM Models）的基类。
        通过继承 `Base`，SQLAlchemy 能够在运行时自动注册模型类，解析字段映射，
        并维护模型元数据（Base.metadata），用于自动生成数据库 Schema 或执行 Alembic 迁移。

    ⚡ 边界与性能思考：
        - 必须保持所有模型都在同一个声明式基类下注册，否则跨模块的 `relationship` 关联将无法正确解析。
        - 全局仅保留一个声明式基类，确保元数据一致性。
    """
    pass


