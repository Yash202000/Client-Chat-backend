"""
Social Widget endpoints (Instagram, Telegram, Messenger floating buttons)

POST   /social-widget            — create widget
GET    /social-widget?channel=   — list company widgets (optionally filter by channel)
GET    /social-widget/{id}       — get single widget
PUT    /social-widget/{id}       — update widget
DELETE /social-widget/{id}       — delete widget
GET    /social-widget/{id}/snippet — get embed HTML snippet

Public (no auth):
GET    /public/social-widget/script/{key}.js — self-contained JS widget
GET    /public/social-widget/config/{key}    — JSON config (CORS-open)
"""
import logging
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.services import social_widget_service

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)

CHANNEL_ICONS = {
    "instagram": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="26" height="26" fill="{color}"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg>',
    "telegram": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="26" height="26" fill="{color}"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>',
    "messenger": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="26" height="26" fill="{color}"><path d="M12 0C5.373 0 0 4.974 0 11.111c0 3.498 1.744 6.614 4.469 8.654V24l4.088-2.242c1.092.301 2.246.464 3.443.464 6.627 0 12-4.974 12-11.111S18.627 0 12 0zm1.191 14.963l-3.055-3.26-5.963 3.26L10.732 8l3.131 3.259L19.752 8l-6.561 6.963z"/></svg>',
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WidgetCreate(BaseModel):
    channel: Literal["instagram", "telegram", "messenger"]
    name: str
    handle: str
    greeting_text: Optional[str] = None
    subtext: Optional[str] = None
    button_label: Optional[str] = None
    button_color: Optional[str] = None
    button_text_color: str = "#FFFFFF"
    position: Literal["bottom-right", "bottom-left"] = "bottom-right"
    show_tooltip: bool = True
    show_agent_avatar: bool = False
    agent_avatar_url: Optional[str] = None
    agent_name: Optional[str] = None


class WidgetUpdate(BaseModel):
    name: Optional[str] = None
    handle: Optional[str] = None
    greeting_text: Optional[str] = None
    subtext: Optional[str] = None
    button_label: Optional[str] = None
    button_color: Optional[str] = None
    button_text_color: Optional[str] = None
    position: Optional[Literal["bottom-right", "bottom-left"]] = None
    show_tooltip: Optional[bool] = None
    show_agent_avatar: Optional[bool] = None
    agent_avatar_url: Optional[str] = None
    agent_name: Optional[str] = None
    is_active: Optional[bool] = None


class WidgetResponse(BaseModel):
    id: int
    widget_key: str
    channel: str
    name: str
    handle: str
    greeting_text: str
    subtext: str
    button_label: str
    button_color: str
    button_text_color: str
    position: str
    show_tooltip: bool
    show_agent_avatar: bool
    agent_avatar_url: Optional[str]
    agent_name: Optional[str]
    is_active: bool
    channel_url: str
    embed_snippet: str


def _backend_url(request: Request) -> str:
    return (settings.BACKEND_URL if hasattr(settings, "BACKEND_URL") and settings.BACKEND_URL else None) \
           or str(request.base_url).rstrip("/")


def _to_response(widget, request: Request) -> WidgetResponse:
    bu = _backend_url(request)
    return WidgetResponse(
        id=widget.id,
        widget_key=widget.widget_key,
        channel=widget.channel,
        name=widget.name,
        handle=widget.handle,
        greeting_text=widget.greeting_text,
        subtext=widget.subtext,
        button_label=widget.button_label,
        button_color=widget.button_color,
        button_text_color=widget.button_text_color,
        position=widget.position,
        show_tooltip=widget.show_tooltip,
        show_agent_avatar=widget.show_agent_avatar,
        agent_avatar_url=widget.agent_avatar_url,
        agent_name=widget.agent_name,
        is_active=widget.is_active,
        channel_url=social_widget_service.build_channel_url(widget),
        embed_snippet=social_widget_service.build_embed_snippet(widget, bu),
    )


# ---------------------------------------------------------------------------
# Protected endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=WidgetResponse, status_code=201)
def create_widget(
    request: Request,
    body: WidgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    data = body.model_dump()
    widget = social_widget_service.create_widget(db, company_id=x_company_id, **data)
    return _to_response(widget, request)


@router.get("", response_model=List[WidgetResponse])
def list_widgets(
    request: Request,
    channel: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    return [_to_response(w, request) for w in social_widget_service.list_widgets(db, x_company_id, channel)]


@router.get("/{widget_id}", response_model=WidgetResponse)
def get_widget(
    request: Request,
    widget_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    widget = social_widget_service.get_widget(db, widget_id, x_company_id)
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found.")
    return _to_response(widget, request)


@router.put("/{widget_id}", response_model=WidgetResponse)
def update_widget(
    request: Request,
    widget_id: int,
    body: WidgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    widget = social_widget_service.update_widget(
        db, widget_id, x_company_id, **body.model_dump(exclude_none=True)
    )
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found.")
    return _to_response(widget, request)


@router.delete("/{widget_id}", status_code=204)
def delete_widget(
    widget_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    deleted = social_widget_service.delete_widget(db, widget_id, x_company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Widget not found.")


@router.get("/{widget_id}/snippet")
def get_snippet(
    request: Request,
    widget_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    widget = social_widget_service.get_widget(db, widget_id, x_company_id)
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found.")
    return {"snippet": social_widget_service.build_embed_snippet(widget, _backend_url(request))}


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@public_router.get("/config/{widget_key}")
def get_public_config(widget_key: str, db: Session = Depends(get_db)):
    widget = social_widget_service.get_widget_by_key(db, widget_key)
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found.")
    return JSONResponse(
        content={
            "channel": widget.channel,
            "handle": widget.handle,
            "greeting_text": widget.greeting_text,
            "subtext": widget.subtext,
            "button_label": widget.button_label,
            "button_color": widget.button_color,
            "button_text_color": widget.button_text_color,
            "position": widget.position,
            "show_tooltip": widget.show_tooltip,
            "show_agent_avatar": widget.show_agent_avatar,
            "agent_avatar_url": widget.agent_avatar_url or "",
            "agent_name": widget.agent_name or "",
            "channel_url": social_widget_service.build_channel_url(widget),
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


@public_router.get("/script/{widget_key}.js")
def get_widget_script(widget_key: str, db: Session = Depends(get_db)):
    widget = social_widget_service.get_widget_by_key(db, widget_key)
    if not widget:
        return Response(content="/* Widget not found */", media_type="application/javascript")

    channel_url = social_widget_service.build_channel_url(widget)
    pos = widget.position
    side = "right: 24px;" if "right" in pos else "left: 24px;"
    tooltip_side = "right: 80px;" if "right" in pos else "left: 80px;"

    icon_template = CHANNEL_ICONS.get(widget.channel, CHANNEL_ICONS["messenger"])
    icon_svg = icon_template.replace("{color}", widget.button_text_color)

    avatar_html = ""
    if widget.show_agent_avatar and widget.agent_avatar_url:
        avatar_html = f'<img src="{widget.agent_avatar_url}" style="width:32px;height:32px;border-radius:50%;margin-right:10px;object-fit:cover;" />'

    name_html = (
        f'<span style="font-size:13px;color:#555;display:block;">{widget.agent_name}</span>'
        if widget.agent_name else ""
    )

    tooltip_html = ""
    if widget.show_tooltip:
        tooltip_html = f"""
        var tooltip = document.createElement('div');
        tooltip.id = '__sw_tooltip_{widget_key}';
        tooltip.innerHTML = '<div style="display:flex;align-items:center;">{avatar_html}<div><strong style=\\"font-size:14px;color:#111;\\">{widget.greeting_text}</strong>{name_html}<span style=\\"font-size:12px;color:#888;\\">{widget.subtext}</span></div></div>';
        tooltip.style.cssText = 'position:fixed;bottom:90px;{tooltip_side}background:#fff;border-radius:12px;padding:14px 16px;box-shadow:0 4px 20px rgba(0,0,0,0.15);z-index:99998;max-width:260px;cursor:pointer;display:none;font-family:sans-serif;';
        tooltip.onclick = function(){{ window.open('{channel_url}','_blank'); }};
        document.body.appendChild(tooltip);
        setTimeout(function(){{ tooltip.style.display='block'; }}, 2000);
        btn.addEventListener('click', function(){{ tooltip.style.display='none'; }});
        """

    js = f"""
(function() {{
  if (document.getElementById('__sw_widget_{widget_key}')) return;
  var btn = document.createElement('a');
  btn.id = '__sw_widget_{widget_key}';
  btn.href = '{channel_url}';
  btn.target = '_blank';
  btn.rel = 'noopener noreferrer';
  btn.title = '{widget.button_label}';
  btn.innerHTML = '{icon_svg}';
  btn.style.cssText = 'position:fixed;bottom:24px;{side}width:56px;height:56px;background:{widget.button_color};border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(0,0,0,0.25);z-index:99999;cursor:pointer;text-decoration:none;transition:transform .2s;';
  btn.onmouseover = function(){{ this.style.transform='scale(1.1)'; }};
  btn.onmouseout  = function(){{ this.style.transform='scale(1)'; }};
  document.body.appendChild(btn);
  {tooltip_html}
}})();
"""
    return Response(
        content=js,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"},
    )
