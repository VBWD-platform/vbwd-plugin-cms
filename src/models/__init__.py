"""CMS models — import all to register with SQLAlchemy."""
from plugins.cms.src.models.cms_image import CmsImage  # noqa: F401
from plugins.cms.src.models.cms_style import CmsStyle  # noqa: F401
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: F401
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: F401
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget  # noqa: F401
from plugins.cms.src.models.cms_menu_item import CmsMenuItem  # noqa: F401
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule  # noqa: F401
from plugins.cms.src.models.cms_geo_block_config import (  # noqa: F401
    CmsGeoBlockConfig,
)
from plugins.cms.src.models.cms_post import CmsPost  # noqa: F401
from plugins.cms.src.models.cms_post_widget import CmsPostWidget  # noqa: F401
from plugins.cms.src.models.cms_post_content_block import (  # noqa: F401
    CmsPostContentBlock,
)
from plugins.cms.src.models.cms_term import CmsTerm  # noqa: F401
from plugins.cms.src.models.cms_post_term import CmsPostTerm  # noqa: F401
