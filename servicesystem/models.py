from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from servicesystem.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    short_name = db.Column(db.String(64))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    contracts = db.relationship("Contract", back_populates="organization", lazy="dynamic")


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    number = db.Column(db.String(64), nullable=False, unique=True)
    signed_at = db.Column(db.Date)
    service_end_date = db.Column(db.Date)
    status = db.Column(db.String(32), nullable=False, default="active_warranty")
    master_login = db.Column(db.String(64), nullable=False)
    master_password_hash = db.Column(db.String(255), nullable=False)
    master_key_expires_at = db.Column(db.Date)
    notes = db.Column(db.Text)
    document_url = db.Column(db.String(512))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    organization = db.relationship("Organization", back_populates="contracts")
    users = db.relationship("User", back_populates="contract", lazy="dynamic")
    content_access = db.relationship("ContractContentAccess", back_populates="contract", lazy="dynamic")

    def set_master_password(self, password: str):
        self.master_password_hash = generate_password_hash(password)

    def check_master_password(self, password: str) -> bool:
        return check_password_hash(self.master_password_hash, password)

    @property
    def is_expired(self) -> bool:
        if not self.service_end_date:
            return False
        return self.service_end_date < datetime.now().date()

    @property
    def is_master_key_expired(self) -> bool:
        if not self.master_key_expires_at:
            return False
        return self.master_key_expires_at < datetime.now().date()

    @property
    def is_blocked(self) -> bool:
        if self.status == "terminated":
            return True
        if self.is_expired and self.status in ("active_warranty", "active_post_warranty"):
            return True
        return False

    @property
    def is_readonly(self) -> bool:
        return self.status == "suspended"

    @property
    def is_active_access(self) -> bool:
        return self.status in ("active_warranty", "active_post_warranty")

    @property
    def days_until_expiry(self):
        if not self.service_end_date:
            return None
        return (self.service_end_date - datetime.now().date()).days


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    position = db.Column(db.String(255))
    phone = db.Column(db.String(32))
    role = db.Column(db.String(32), nullable=False, default="customer")
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"))
    is_active = db.Column(db.Boolean, default=True)
    pd_consent_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    contract = db.relationship("Contract", back_populates="users")
    organization = db.relationship("Organization")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_staff(self) -> bool:
        return self.role in ("admin", "auditor", "executor")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_auditor(self) -> bool:
        return self.role == "auditor"

    @property
    def is_executor(self) -> bool:
        return self.role == "executor"

    @property
    def is_customer(self) -> bool:
        return self.role == "customer"


class ObjectCategory(db.Model):
    __tablename__ = "object_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    incidents = db.relationship("IncidentCategory", back_populates="object_category", lazy="dynamic")
    routing = db.relationship("ObjectCategoryRouting", back_populates="object_category", uselist=False)


class ObjectCategoryRouting(db.Model):
    """Ticket routing: auditor (and optional default executor) per object category (TZ 3.3.7)."""
    __tablename__ = "object_category_routing"

    id = db.Column(db.Integer, primary_key=True)
    object_category_id = db.Column(db.Integer, db.ForeignKey("object_categories.id"), unique=True, nullable=False)
    auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    default_executor_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    object_category = db.relationship("ObjectCategory", back_populates="routing")
    auditor = db.relationship("User", foreign_keys=[auditor_id])
    default_executor = db.relationship("User", foreign_keys=[default_executor_id])


class IncidentCategory(db.Model):
    __tablename__ = "incident_categories"

    id = db.Column(db.Integer, primary_key=True)
    object_category_id = db.Column(db.Integer, db.ForeignKey("object_categories.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    object_category = db.relationship("ObjectCategory", back_populates="incidents")


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    executor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    object_category_id = db.Column(db.Integer, db.ForeignKey("object_categories.id"), nullable=False)
    incident_category_id = db.Column(db.Integer, db.ForeignKey("incident_categories.id"), nullable=False)
    priority = db.Column(db.Integer, nullable=False, default=2)
    priority_changed = db.Column(db.Boolean, default=False)
    priority_change_reason = db.Column(db.Text)
    subject = db.Column(db.String(120), nullable=False)
    description_md = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="new")
    response_text_md = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reaction_deadline = db.Column(db.DateTime(timezone=True))
    resolution_deadline = db.Column(db.DateTime(timezone=True))
    timer1_started_at = db.Column(db.DateTime(timezone=True))
    timer1_stopped_at = db.Column(db.DateTime(timezone=True))
    timer1_total_seconds = db.Column(db.Integer, default=0)
    timer2_started_at = db.Column(db.DateTime(timezone=True))
    timer2_stopped_at = db.Column(db.DateTime(timezone=True))
    timer2_total_seconds = db.Column(db.Integer, default=0)
    resolved_at = db.Column(db.DateTime(timezone=True))

    @property
    def timer_total_seconds(self) -> int:
        return (self.timer1_total_seconds or 0) + (self.timer2_total_seconds or 0)

    contract = db.relationship("Contract")
    author = db.relationship("User", foreign_keys=[author_id])
    auditor = db.relationship("User", foreign_keys=[auditor_id])
    executor = db.relationship("User", foreign_keys=[executor_id])
    object_category = db.relationship("ObjectCategory")
    incident_category = db.relationship("IncidentCategory")
    attachments = db.relationship("TicketAttachment", back_populates="ticket", lazy="dynamic")
    history = db.relationship("TicketHistory", back_populates="ticket", lazy="dynamic", order_by="TicketHistory.created_at")
    response_files = db.relationship("TicketResponseFile", back_populates="ticket", lazy="dynamic")


class TicketAttachment(db.Model):
    __tablename__ = "ticket_attachments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True)
    original_name = db.Column(db.String(512), nullable=False)
    stored_name = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(128))
    size_bytes = db.Column(db.BigInteger, default=0)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    ticket = db.relationship("Ticket", back_populates="attachments")


class TicketResponseFile(db.Model):
    __tablename__ = "ticket_response_files"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True)
    original_name = db.Column(db.String(512), nullable=False)
    stored_name = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(128))
    size_bytes = db.Column(db.BigInteger, default=0)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    ticket = db.relationship("Ticket", back_populates="response_files")


class TicketHistory(db.Model):
    __tablename__ = "ticket_history"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(64), nullable=False)
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)

    ticket = db.relationship("Ticket", back_populates="history")
    user = db.relationship("User")


class Plugin(db.Model):
    __tablename__ = "plugins"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text)
    min_core_version = db.Column(db.String(32))
    max_core_version = db.Column(db.String(32))
    current_version = db.Column(db.String(32))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    versions = db.relationship("PluginVersion", back_populates="plugin", lazy="dynamic", order_by="PluginVersion.created_at.desc()")


class PluginVersion(db.Model):
    __tablename__ = "plugin_versions"

    id = db.Column(db.Integer, primary_key=True)
    plugin_id = db.Column(db.Integer, db.ForeignKey("plugins.id"), nullable=False)
    version = db.Column(db.String(32), nullable=False)
    changelog_md = db.Column(db.Text)
    stored_name = db.Column(db.String(512), nullable=False)
    original_name = db.Column(db.String(512), nullable=False)
    size_bytes = db.Column(db.BigInteger, default=0)
    is_current = db.Column(db.Boolean, default=False)
    is_archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    plugin = db.relationship("Plugin", back_populates="versions")


class Tutorial(db.Model):
    __tablename__ = "tutorials"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(512), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False)
    category = db.Column(db.String(128))
    tags = db.Column(db.String(512))
    content_md = db.Column(db.Text, nullable=False)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VideoTutorial(db.Model):
    __tablename__ = "video_tutorials"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(512), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False)
    category = db.Column(db.String(128))
    description = db.Column(db.Text)
    video_url = db.Column(db.String(1024))
    video_file = db.Column(db.String(512))
    duration_sec = db.Column(db.Integer)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    chapters = db.relationship("VideoChapter", back_populates="video", lazy="dynamic", order_by="VideoChapter.sort_order")


class VideoChapter(db.Model):
    __tablename__ = "video_chapters"

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("video_tutorials.id"), nullable=False)
    title = db.Column(db.String(512), nullable=False)
    start_sec = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)

    video = db.relationship("VideoTutorial", back_populates="chapters")


class ContractContentAccess(db.Model):
    __tablename__ = "contract_content_access"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False)
    content_type = db.Column(db.String(32), nullable=False)
    content_id = db.Column(db.Integer, nullable=False)

    contract = db.relationship("Contract", back_populates="content_access")

    __table_args__ = (
        db.UniqueConstraint("contract_id", "content_type", "content_id", name="uq_contract_content"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    action = db.Column(db.String(64), nullable=False)
    resource_type = db.Column(db.String(64))
    resource_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)

    user = db.relationship("User")


class UploadSession(db.Model):
    __tablename__ = "upload_sessions"

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    original_name = db.Column(db.String(512), nullable=False)
    stored_name = db.Column(db.String(512), nullable=False)
    total_size = db.Column(db.BigInteger, default=0)
    received_bytes = db.Column(db.BigInteger, default=0)
    mime_type = db.Column(db.String(128))
    context = db.Column(db.String(32))
    context_id = db.Column(db.Integer)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
