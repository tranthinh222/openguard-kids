from pathlib import Path
from fastapi.templating import Jinja2Templates
from app.core.config import settings
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / "dashboard" / "templates"))
templates.env.globals['asset_version'] = quote(settings.asset_version, safe='')
templates.env.globals['asset_imports'] = {
    f'/static/js/{path.name}': f'/static/js/{path.name}?v={quote(settings.asset_version, safe="")}'
    for path in (BASE_DIR / 'dashboard' / 'static' / 'js').glob('*.js')
}
