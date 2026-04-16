"""CMS models — import all to register with SQLAlchemy."""
from plugins.cms.src.models.cms_category import CmsCategory  # noqa: F401
from plugins.cms.src.models.cms_image import CmsImage  # noqa: F401
from plugins.cms.src.models.cms_style import CmsStyle  # noqa: F401
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: F401
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: F401
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget  # noqa: F401
from plugins.cms.src.models.cms_menu_item import CmsMenuItem  # noqa: F401
from plugins.cms.src.models.cms_page_content_block import (  # noqa: F401
    CmsPageContentBlock,
)
from plugins.cms.src.models.cms_page import CmsPage  # noqa: F401
from plugins.cms.src.models.cms_page_widget import CmsPageWidget  # noqa: F401
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule  # noqa: F401
