from app.core.content import (
    blocks_to_text,
    html_to_blocks,
    html_to_text,
    markdown_to_html,
    normalize_content,
    sanitize_html,
    text_to_html,
)
from app.models import ContentFormat


def test_sanitize_strips_dangerous_markup() -> None:
    dirty = (
        '<p onclick="evil()">hi</p><script>alert(1)</script>'
        '<a href="javascript:alert(1)">bad</a><a href="https://ok.test/x">ok</a>'
        '<img src="data:image/png;base64,AAAA"><iframe src="x"></iframe>'
        '<p style="color:red">red</p><p style="text-align: center">centered</p>'
    )
    clean = sanitize_html(dirty)
    assert "<script" not in clean and "onclick" not in clean and "<iframe" not in clean
    assert 'href="javascript' not in clean
    assert 'href="https://ok.test/x"' in clean and 'rel="noopener noreferrer"' in clean
    assert 'src="data:' not in clean
    assert 'style="color' not in clean
    assert 'style="text-align: center"' in clean


def test_sanitize_keeps_editor_markup() -> None:
    html = (
        '<div data-panel="" data-panel-type="info" class="kb-panel kb-panel-info"><p>Note</p></div>'
        '<ul data-type="taskList"><li data-type="taskItem" data-checked="true">'
        '<label><input type="checkbox" checked></label><div><p>Done</p></div></li></ul>'
        '<pre><code class="language-python">print(1)</code></pre>'
        '<table><tbody><tr><th colspan="2" colwidth="120">h</th></tr></tbody></table>'
        '<img src="/api/v1/attachments/abc/download" data-attachment-id="abc" alt="pic" width="300">'
        "<mark>hl</mark><sub>s</sub><sup>p</sup>"
    )
    clean = sanitize_html(html)
    for needle in [
        'data-panel-type="info"',
        'class="kb-panel kb-panel-info"',
        'data-type="taskList"',
        'data-checked="true"',
        'type="checkbox"',
        'class="language-python"',
        'colwidth="120"',
        'data-attachment-id="abc"',
        'src="/api/v1/attachments/abc/download"',
        "<mark>",
        "<sub>",
    ]:
        assert needle in clean, needle
    # non-checkbox inputs are neutralised
    assert 'type="text"' not in sanitize_html('<input type="text" value="x">')


def test_html_to_blocks_and_text() -> None:
    html = (
        "<h1>Title</h1><p>Para one</p><ul><li>a<ul><li>nested</li></ul></li><li>b</li></ul>"
        "<ol><li>first</li><li>second</li></ol>"
        "<table><tr><th>c1</th><th>c2</th></tr><tr><td>1</td><td>2</td></tr></table>"
        "<pre><code>x = 1\ny = 2</code></pre><blockquote><p>quoted</p></blockquote>"
        '<ul data-type="taskList"><li data-type="taskItem" data-checked="false"><label><input type="checkbox"></label><div><p>todo</p></div></li></ul>'
        "<p>line<br>break</p><hr><img alt='an image'>"
    )
    blocks = html_to_blocks(html)
    kinds = [(b.kind, b.text) for b in blocks]
    assert kinds[0] == ("heading", "Title")
    assert blocks[0].level == 1
    assert ("paragraph", "Para one") in kinds
    assert ("list_item", "- a") in kinds
    assert ("list_item", "  - nested") in kinds
    assert ("list_item", "1. first") in kinds and ("list_item", "2. second") in kinds
    assert ("table_row", "c1 | c2") in kinds and ("table_row", "1 | 2") in kinds
    assert ("code", "x = 1\ny = 2") in kinds
    assert ("quote", "quoted") in kinds
    assert ("list_item", "[ ] todo") in kinds
    assert ("paragraph", "line break") in kinds
    assert ("other", "an image") in kinds
    text = blocks_to_text(blocks)
    assert text.startswith("Title\n\nPara one")
    assert html_to_text("") == ""
    assert html_to_text("   ") == ""


def test_markdown_and_text_conversion() -> None:
    html = markdown_to_html(
        "# H\n\n~~gone~~ **bold**\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    )
    assert "<h1>H</h1>" in html and "<s>gone</s>" in html and "<table>" in html
    assert text_to_html("a\nb\n\nc & <d>") == "<p>a<br>b</p><p>c &amp; &lt;d&gt;</p>"
    assert text_to_html("   ") == ""


def test_normalize_content_roundtrip() -> None:
    html, text = normalize_content(
        "# Hello\n\nworld <script>x</script>", ContentFormat.markdown
    )
    assert html.startswith("<h1>Hello</h1>") and "<script" not in html
    assert text == "Hello\n\nworld"
    html, text = normalize_content("plain\n\ntext", ContentFormat.text)
    assert html == "<p>plain</p><p>text</p>" and text == "plain\n\ntext"
    html, text = normalize_content("", ContentFormat.html)
    assert html == "" and text == ""
