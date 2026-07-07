"""S122 §5a — the prerender writer removes the orphaned old file on a rename.

When a post's permalink MOVES (its ``slug`` changes), the ``content.changed``
payload carries ``previous_slug``. The writer must write the new static file AND
delete the old one, so the old URL never keeps serving a stale 200 that competes
with the new page + its 301. The removal happens AFTER the write, so there is
never a window with neither file present. A save that did NOT move the slug (no
``previous_slug``) must leave every other file untouched.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov (a payload without ``previous_slug`` behaves exactly as before —
no spurious removals); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


class _Post:
    def __init__(self, slug):
        self.id = "p1"
        self.type = "post"
        self.slug = slug
        self.title = "Title"
        self.content_html = "<p>Body</p>"
        self.status = POST_STATUS_PUBLISHED
        self.language = "en"
        self.robots = "index,follow"
        self.seo_excluded = False
        self.meta_title = "Title"
        self.meta_description = "Desc"
        self.meta_keywords = None
        self.og_title = None
        self.og_description = None
        self.og_image_url = None
        self.canonical_url = None
        self.schema_json = None
        self.translation_group_id = None
        self.terms = []


class _Loader:
    def __init__(self, post):
        self._post = post

    def load(self, post_id):
        return (self._post, self._post.terms, [])


def _seo_file(tmp_path, slug):
    return tmp_path / "seo" / f"{slug}.html"


def test_rename_writes_new_and_removes_old_nested_path(tmp_path):
    post = _Post(slug="blog/electronics/new-post")
    writer = SeoPrerenderWriter(var_dir=str(tmp_path), post_loader=_Loader(post))

    # Pre-existing old static file (a nested path from a prior permalink).
    old = _seo_file(tmp_path, "blog/electronics/old-post")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("<html>old</html>")

    writer.handle_content_changed(
        {
            "post_id": post.id,
            "type": post.type,
            "slug": post.slug,
            "status": post.status,
            "reason": "updated",
            "previous_slug": "blog/electronics/old-post",
        }
    )

    assert _seo_file(tmp_path, "blog/electronics/new-post").exists()
    assert not old.exists()


def test_no_previous_slug_leaves_other_files_untouched(tmp_path):
    post = _Post(slug="blog/electronics/my-post")
    writer = SeoPrerenderWriter(var_dir=str(tmp_path), post_loader=_Loader(post))

    sibling = _seo_file(tmp_path, "blog/electronics/other-post")
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text("<html>other</html>")

    writer.handle_content_changed(
        {
            "post_id": post.id,
            "type": post.type,
            "slug": post.slug,
            "status": post.status,
            "reason": "updated",
        }
    )

    assert _seo_file(tmp_path, "blog/electronics/my-post").exists()
    assert sibling.exists()
