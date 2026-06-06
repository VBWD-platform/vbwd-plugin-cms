"""CmsPostContentBlock repository — mirror of the legacy page content-block
upsert (S55).

The legacy ``CmsPageService._apply_data`` upserts content blocks keyed by
``(page_id, area_name)``: an existing area is updated in place, a new area is
inserted. This repository carries the same semantics for ``cms_post`` behind a
narrow port so the service depends on the abstraction, not the model.
"""
from typing import List, Dict, Any
from plugins.cms.src.models.cms_post_content_block import CmsPostContentBlock


class CmsPostContentBlockRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_post(self, post_id: str) -> List[CmsPostContentBlock]:
        return (
            self.session.query(CmsPostContentBlock)
            .filter(CmsPostContentBlock.post_id == post_id)
            .order_by(CmsPostContentBlock.sort_order.asc())
            .all()
        )

    def replace_for_post(
        self, post_id: str, blocks: List[Dict[str, Any]]
    ) -> List[CmsPostContentBlock]:
        """Upsert content blocks keyed by ``(post_id, area_name)``.

        Each block is matched by ``area_name``: an existing area is updated in
        place; a new area is inserted. Mirrors the legacy page upsert (omitted
        areas are left untouched).
        """
        existing = {block.area_name: block for block in self.find_by_post(post_id)}
        result = []
        for block_data in blocks:
            area_name = block_data["area_name"]
            block = existing.get(area_name)
            if block is None:
                block = CmsPostContentBlock()
                block.post_id = post_id
                block.area_name = area_name
                self.session.add(block)
            if "content_json" in block_data:
                block.content_json = block_data["content_json"]
            if "content_html" in block_data:
                block.content_html = block_data["content_html"]
            if "source_css" in block_data:
                block.source_css = block_data["source_css"]
            if "sort_order" in block_data:
                block.sort_order = block_data["sort_order"]
            result.append(block)
        self.session.flush()
        self.session.commit()
        return result
