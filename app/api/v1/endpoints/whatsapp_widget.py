"""
WhatsApp Widget endpoints

POST   /wa-widget           — create widget
GET    /wa-widget           — list company widgets
GET    /wa-widget/{id}      — get single widget
PUT    /wa-widget/{id}      — update widget
DELETE /wa-widget/{id}      — delete widget
GET    /wa-widget/{id}/snippet — get embed HTML snippet

Public (no auth):
GET    /public/wa-widget/script/{key}.js — serves self-contained JS widget
GET    /public/wa-widget/config/{key}    — serves widget JSON config (CORS-open)
"""
import logging
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.services import whatsapp_widget_service

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WidgetCreate(BaseModel):
    name: str
    phone_number: str
    prefill_message: Optional[str] = None
    greeting_text: str = "Chat with us on WhatsApp!"
    subtext: str = "Typically replies within minutes"
    button_label: str = "Chat on WhatsApp"
    button_color: str = "#25D366"
    button_text_color: str = "#FFFFFF"
    position: Literal["bottom-right", "bottom-left"] = "bottom-right"
    show_tooltip: bool = True
    show_agent_avatar: bool = False
    agent_avatar_url: Optional[str] = None
    agent_name: Optional[str] = None


class WidgetUpdate(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    prefill_message: Optional[str] = None
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
    name: str
    phone_number: str
    prefill_message: Optional[str]
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
    wa_url: str
    embed_snippet: str


def _to_response(widget, request: Request) -> WidgetResponse:
    backend_url = (settings.BACKEND_URL if hasattr(settings, "BACKEND_URL") and settings.BACKEND_URL else None) \
                  or str(request.base_url).rstrip("/")
    return WidgetResponse(
        id=widget.id,
        widget_key=widget.widget_key,
        name=widget.name,
        phone_number=widget.phone_number,
        prefill_message=widget.prefill_message,
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
        wa_url=whatsapp_widget_service.build_wa_url(widget),
        embed_snippet=whatsapp_widget_service.build_embed_snippet(widget, backend_url),
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
    widget = whatsapp_widget_service.create_widget(db, company_id=x_company_id, **body.model_dump())
    return _to_response(widget, request)


@router.get("", response_model=List[WidgetResponse])
def list_widgets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    return [_to_response(w, request) for w in whatsapp_widget_service.list_widgets(db, x_company_id)]


@router.get("/{widget_id}", response_model=WidgetResponse)
def get_widget(
    request: Request,
    widget_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    widget = whatsapp_widget_service.get_widget(db, widget_id, x_company_id)
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
    widget = whatsapp_widget_service.update_widget(
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
    deleted = whatsapp_widget_service.delete_widget(db, widget_id, x_company_id)
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
    widget = whatsapp_widget_service.get_widget(db, widget_id, x_company_id)
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found.")
    backend_url = (settings.BACKEND_URL if hasattr(settings, "BACKEND_URL") and settings.BACKEND_URL else None) \
                  or str(request.base_url).rstrip("/")
    return {"snippet": whatsapp_widget_service.build_embed_snippet(widget, backend_url)}


# ---------------------------------------------------------------------------
# Public endpoints (no auth, CORS-open for customer sites)
# ---------------------------------------------------------------------------

@public_router.get("/config/{widget_key}")
def get_public_config(widget_key: str, db: Session = Depends(get_db)):
    """Returns widget JSON config — fetched by the embed script on the customer's site."""
    widget = whatsapp_widget_service.get_widget_by_key(db, widget_key)
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found.")
    return JSONResponse(
        content={
            "phone_number": widget.phone_number,
            "prefill_message": widget.prefill_message or "",
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
            "wa_url": whatsapp_widget_service.build_wa_url(widget),
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


@public_router.get("/script/{widget_key}.js")
def get_widget_script(widget_key: str, db: Session = Depends(get_db)):
    """
    Serves a self-contained JS snippet.
    Customer pastes: <script src=".../{key}.js" async></script>
    """
    widget = whatsapp_widget_service.get_widget_by_key(db, widget_key)
    if not widget:
        return Response(content="/* Widget not found */", media_type="application/javascript")

    wa_url = whatsapp_widget_service.build_wa_url(widget)
    pos = widget.position  # bottom-right | bottom-left
    side = "right: 24px;" if "right" in pos else "left: 24px;"
    tooltip_side = "right: 80px;" if "right" in pos else "left: 80px;"

    avatar_html = ""
    if widget.show_agent_avatar and widget.agent_avatar_url:
        avatar_html = f'<img src="{widget.agent_avatar_url}" style="width:32px;height:32px;border-radius:50%;margin-right:10px;object-fit:cover;" />'

    name_html = f'<span style="font-size:13px;color:#555;display:block;">{widget.agent_name}</span>' if widget.agent_name else ""

    tooltip_html = ""
    if widget.show_tooltip:
        tooltip_html = f"""
        var tooltip = document.createElement('div');
        tooltip.id = '__wa_tooltip_{widget_key}';
        tooltip.innerHTML = '<div style="display:flex;align-items:center;">{avatar_html}<div><strong style=\\"font-size:14px;color:#111;\\">{widget.greeting_text}</strong>{name_html}<span style=\\"font-size:12px;color:#888;\\">{widget.subtext}</span></div></div>';
        tooltip.style.cssText = 'position:fixed;bottom:90px;{tooltip_side}background:#fff;border-radius:12px;padding:14px 16px;box-shadow:0 4px 20px rgba(0,0,0,0.15);z-index:99998;max-width:260px;cursor:pointer;display:none;font-family:sans-serif;';
        tooltip.onclick = function(){{ window.open('{wa_url}','_blank'); }};
        document.body.appendChild(tooltip);
        setTimeout(function(){{ tooltip.style.display='block'; }}, 2000);
        btn.addEventListener('click', function(){{ tooltip.style.display='none'; }});
        """

    js = f"""
(function() {{
  if (document.getElementById('__wa_widget_{widget_key}')) return;
  var btn = document.createElement('a');
  btn.id = '__wa_widget_{widget_key}';
  btn.href = '{wa_url}';
  btn.target = '_blank';
  btn.rel = 'noopener noreferrer';
  btn.title = '{widget.button_label}';
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28" fill="{widget.button_text_color}"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/><path d="M12 0C5.373 0 0 5.373 0 12c0 2.127.558 4.122 1.533 5.854L.057 23.448a.75.75 0 0 0 .916.916l5.594-1.476A11.953 11.953 0 0 0 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.907 0-3.686-.528-5.208-1.443l-.374-.222-3.878 1.023 1.023-3.878-.222-.374A9.953 9.953 0 0 1 2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/></svg>';
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
