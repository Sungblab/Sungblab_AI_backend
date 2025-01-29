# Import all the models, so that Base has them before being imported by Alembic
from app.db.base_class import Base  # noqa
from app.models.user import User  # noqa
from app.models.email_verification import EmailVerification  # noqa
from app.models.subscription import Subscription  # noqa
from app.models.chat_room import ChatRoom  # noqa
from app.models.chat import ChatMessage  # noqa
from app.models.project import Project, ProjectChat, ProjectMessage  # noqa
from app.models.stats import TokenUsage  # noqa

# Make sure all models are imported before initializing Base.metadata
# This is required for Alembic to detect all models 