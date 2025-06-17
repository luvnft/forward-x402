import json
import base64
import shutil
import datetime as dt
import logging
import os
from decimal import Decimal
from dotenv import load_dotenv

from fasthtml.common import *
from fasthtml.oauth import GoogleAppClient, OAuth
from fastcore.all import *
from monsterui.all import *

import db
import x402

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()


SERVER_URL = 'http://localhost:5001'

cli = GoogleAppClient.from_file('client_secret.json')
class Auth(OAuth):
    def get_auth(self, info, ident, session, state):
        email = info.email or ''
        if info.email_verified and email.split('@')[-1]=='fewsats.com':
            # Ensure user exists and set current user context
            db.ensure_user(info.sub, info.email, info.name, info.picture)
            return RedirectResponse('/', status_code=303)

hdrs = (
    Theme.blue.headers(),
    Link(rel='stylesheet', href='/static/style.css', type='text/css')
)


app = FastHTML(hdrs=hdrs)
rt = app.route

# Mount fixed "static/" folder under /static
#    → Serves files like /static/img/logo.png or /static/css/style.css :contentReference[oaicite:12]{index=12}.
app.static_route_exts(prefix='/static', static_path='static', exts='static')

# Mount user-uploads folder under /files
app.static_route_exts(prefix='/files', static_path='data/files', exts='static')

# Skip routes that don't need authentication (otherwise they'll return a 303 redirect)
skip = ('/login', '/logout', '/redirect', '/static', '/files/.*/.*', '/forward/.*')
oauth = Auth(app, cli, skip=skip)


data_dir = Path("data/files")

def UserMenu(email: str): return DivHStacked(P(email), A("Logout", href="/logout"))

@app.get('/login')
def login(req): 
    return (
        Title("Forward X402 - Login"),
        Favicon("https://icons-8e9.pages.dev/favicon-black.svg", "https://icons-8e9.pages.dev/favicon.svg"),
        DivVStacked(
            Img(src="https://icons-8e9.pages.dev/favicon-black.svg", width=100),
            DivVStacked(
                H1('Forward X402', cls="text-center"),
                P("Forget spammy emails with low signal. If someone really needs your atttention let them pay for it.", cls=TextPresets.muted_sm + " text-center"),
                A(Button("Log in with Google"), href=oauth.login_link(req))
            ),
            cls="pt-[20vh]",
        ),
    )

@app.get('/logout')
def logout(session):
    session.pop('auth', None)
    return RedirectResponse('/login', status_code=303)

def NavBar(user):
    return Div(
        A(
            Img(src="https://icons-8e9.pages.dev/favicon-black.svg", width=40),
            H1('Forward X402', href="/"), 
            href="/"
        ),
        UserMenu(user.email),
        cls="header-container"
    )

@app.get
def index(auth):
    user = db.get_user(auth)
    endpoints = db.list_endpoints_by_user(auth)
    
    return (Title("Email Endpoints - Dashboard"),
            Favicon("https://icons-8e9.pages.dev/favicon-black.svg", "https://icons-8e9.pages.dev/favicon.svg"), 
            Container(
                NavBar(user),
                CreateEndpointForm(),
                EndpointsContainer(endpoints),
            )
        )


def EndpointsContainer(endpoints):
    return Card(
        H3("Email Endpoints"),
        EndpointsTable(endpoints),
        id="endpoints-container"
    )
def EndpointRow(endpoint):
    share_url = f"{SERVER_URL}/forward/{endpoint.short_url}"
    return Tr(
            Td(endpoint.email),
            Td(endpoint.label or "-"),
            Td(A(share_url, href=share_url, target="_blank", cls="text-sm")),
            Td(f"${endpoint.base_price:.6f}"),
            Td("Active" if endpoint.is_active else "Inactive"),
            Td(str(endpoint.hit_count)),
            Td(str(endpoint.payment_count)),
            Td(endpoint.created_at.split('T')[0] if 'T' in endpoint.created_at else endpoint.created_at)
        )

def EndpointsTable(endpoints):
    if not endpoints: return P("No endpoints yet", cls=TextPresets.muted_lg)
    return Card(
        Table(
            Thead(
                Tr(
                    Th("Email"),
                    Th("Label"),
                    Th("Share Link"),
                    Th("Base Price"),
                    Th("Status"),
                    Th("Hits"),
                    Th("Payments"),
                    Th("Created")
                )
            ),
            Tbody(
                *[EndpointRow(endpoint) for endpoint in endpoints]
            ),
        )
    )

def CreateEndpointForm():
    return Form(
        Card(
            DivHStacked(
                Input(placeholder="Email address", name="email", required=True),
                Input(placeholder="Label users will see when sharing (e.g. your name)", name="label", required=True),
                Input(type="float", placeholder="Price in USDC", name="base_price", required=True),
                Button("Create", type="submit"),
            ),
        ),
        hx_post=create_endpoint,
        hx_target="#endpoints-container",
        hx_swap="outerHTML"
    )

@rt
def create_endpoint(email: str,  base_price: float, label: str = "", auth = ''):
    if base_price <= 0: return "Invalid price"

    base_price = base_price
    
    endpoint_id = db.create_email_endpoint(auth, email, label, base_price)
    endpoints = db.list_endpoints_by_user(auth)
    
    return EndpointsContainer(endpoints)

@app.get("/forward/{short_url}")
def forward_endpoint(short_url: str):
    endpoint = db.get_endpoint_by_short_url(short_url)
    if not endpoint: return
    
    curl_example = f"""curl -X POST {SERVER_URL}/forward/{short_url} \\
  -H "Content-Type: application/json" \\
  -d '{{
    "email": "your@email.com",
    "subject": "Your Subject Here", 
    "message": "Your message content here"
  }}'"""
    
    return DivVStacked(
        Title(f"Forward X402 - {endpoint.label or 'Email Endpoint'}"),
        Container(
            H1(f"Send Email to {endpoint.label}"),
            P(f"Price: ${endpoint.base_price:.6f} USDC"),
            H2("How to Send a Paid Email"),
            P("Send a POST request with your email details to trigger the X402 payment flow:"),
            Pre(Code(curl_example, cls="language-bash")),

        )
    )

@app.post("/forward/{short_url}")
async def forward_payment(short_url: str, request: Request):
    endpoint = db.get_endpoint_by_short_url(short_url)
    db.update_hit_count(endpoint.id)

    if not endpoint: return JSONResponse(status_code=404, content={"error": "Endpoint not found"})
    
    x_payment = request.headers.get("X-PAYMENT")
    user_agent = request.headers.get("User-Agent", "")
    accept_header = request.headers.get("Accept", "")
    
    # Parse JSON payload
    try:
        body = await request.json()
        sender_email = body.get("email")
        subject = body.get("subject") 
        message = body.get("message")
        
        if not all([sender_email, subject, message]):
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required fields: email, subject, message"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON payload"}
        )
    
    # Create payment requirements
    facilitator_config = x402.create_x402_facilitator_config()
    amount = Decimal(str(endpoint.base_price))
    response = None
    try:
        response = await x402.payment_middleware(
            url=str(request.url),
            x_payment=x_payment,
            user_agent=user_agent,
            accept_header=accept_header,
            amount=amount,
            address=os.environ.get("X402_PAYMENT_ADDRESS", ""),
            facilitator_config=facilitator_config,
            description=f"Send email to {endpoint.label}",
            mime_type="application/json",
            max_timeout_seconds=int(os.environ.get("X402_MAX_TIMEOUT_SECONDS", "300")),
            testnet=os.environ.get("ENV", "dev") == "dev",
            resource=f"/forward/{short_url}"
        )
        
        # If payment successful (200 status), send email and update counters
        if response.status_code == 200:
            # TODO: Replace with actual email sending
            logger.info("EMAIL SENT", extra={
                "to": endpoint.email,
                "from": sender_email,
                "subject": subject,
                "message": message,
                "endpoint_id": endpoint.id
            })
            
            db.update_endpoint_counters(endpoint.id, payment_success=True)
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Email sent successfully"
                },
                headers=dict(response.headers)
            )
        else:
            # Return payment requirements or error
            return response
            
    except Exception as e:
        logger.error(f"Payment processing failed {e}", extra={"error": str(e)})
        return JSONResponse(
            status_code=500,
            content={"error": "Payment processing failed"}
        )

serve()