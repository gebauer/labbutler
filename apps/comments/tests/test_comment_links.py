"""The linkify_comment filter: safe rendering of [text](/path) references."""

from django.template import Context, Template

from apps.comments.templatetags.comment_links import linkify_comment


def test_plain_text_is_escaped():
    assert linkify_comment("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_relative_link_becomes_anchor():
    html = linkify_comment("Checked in from [Request #7](/requests/7/).")
    assert html.startswith("Checked in from <a ")
    assert '<a href="/requests/7/"' in html
    assert ">Request #7</a>" in html


def test_multiple_links_render():
    html = linkify_comment("[a](/x/) and [b](/y/)")
    assert html.count("<a ") == 2
    assert '<a href="/x/"' in html and '<a href="/y/"' in html


def test_non_relative_urls_stay_plain_text():
    for body in (
        "[x](https://evil.com)",
        "[x](javascript:alert(1))",
        "[x](mailto:a@b.c)",
        "[x](//evil.com)",
    ):
        html = linkify_comment(body)
        assert "<a " not in html, body


def test_html_in_link_text_is_escaped():
    html = linkify_comment("[<b>bold</b>](/x/)")
    assert "<b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


def test_output_renders_unescaped_through_a_template():
    template = Template("{% load comment_links %}{{ body|linkify_comment }}")
    html = template.render(Context({"body": "see [Request #7](/requests/7/) & <i>note</i>"}))
    assert '<a href="/requests/7/"' in html
    assert "&amp;" in html and "&lt;i&gt;" in html
