"""CmsRoutingRule model — URL routing rules stored in DB."""
from src.extensions import db
from src.models.base import BaseModel


class CmsRoutingRule(BaseModel):
    """A routing rule evaluated by middleware or written to nginx conf."""

    __tablename__ = "cms_routing_rules"

    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    priority = db.Column(db.Integer, default=0, nullable=False)  # lower = first

    # Match condition
    match_type = db.Column(db.String(32), nullable=False)
    # Values per type:
    #   "default"     → match_value = None  (always matches, lowest priority)
    #   "language"    → "de" | "fr" | "es"
    #   "ip_range"    → "203.0.113.0/24"
    #   "country"     → "DE" | "DE,AT,CH"
    #   "path_prefix" → "/old-pricing"
    #   "cookie"      → "vbwd_lang=de"
    match_value = db.Column(db.String(255), nullable=True)

    # Action
    target_slug = db.Column(db.String(255), nullable=False)
    redirect_code = db.Column(db.Integer, default=302, nullable=False)
    is_rewrite = db.Column(db.Boolean, default=False, nullable=False)

    # Evaluation layer
    layer = db.Column(db.String(16), default="middleware", nullable=False)
    # "nginx"      → written into nginx conf
    # "middleware" → evaluated by Flask before_request

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "is_active": self.is_active,
            "priority": self.priority,
            "match_type": self.match_type,
            "match_value": self.match_value,
            "target_slug": self.target_slug,
            "redirect_code": self.redirect_code,
            "is_rewrite": self.is_rewrite,
            "layer": self.layer,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
