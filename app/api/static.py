from pathlib import Path as _StaticPath


_FRONTEND_DIST_DIR = _StaticPath(BASE_DIR) / "sau_frontend" / "dist"

@app.route('/assets/<filename>')
def custom_static(filename):
    return send_from_directory(_FRONTEND_DIST_DIR / 'assets', filename)

# 处理 favicon.ico 静态资源（未来打包用）
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(_FRONTEND_DIST_DIR, 'vidferry-icon.svg')

@app.route('/vite.svg')
def vite_svg():
    return send_from_directory(_FRONTEND_DIST_DIR, 'vite.svg')


@app.route('/vidferry-icon.svg')
def vidferry_icon():
    return send_from_directory(_FRONTEND_DIST_DIR, 'vidferry-icon.svg')

# （未来打包用）
@app.route('/')
def index():  # put application's code here
    return send_from_directory(_FRONTEND_DIST_DIR, 'index.html')

