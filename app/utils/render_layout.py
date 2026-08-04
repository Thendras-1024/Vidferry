"""烧制元素的 1080 x 1920 基准画布缩放工具。"""

RENDER_BASE_WIDTH = 1080
RENDER_BASE_HEIGHT = 1920


def _render_layout_scales(width, height):
    width = max(2, int(width or RENDER_BASE_WIDTH))
    height = max(2, int(height or RENDER_BASE_HEIGHT))
    return width / RENDER_BASE_WIDTH, height / RENDER_BASE_HEIGHT, min(width, height) / RENDER_BASE_WIDTH
