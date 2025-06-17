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
import resend

import db
import x402

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

# Initialize Resend
resend.api_key = os.environ.get("RESEND_API_KEY")


SERVER_URL = 'http://localhost:5001'

cli = GoogleAppClient(client_id=os.environ["CLIENT_ID"],
                      client_secret=os.environ["CLIENT_SECRET"],
                      project_id=os.environ["PROJECT_ID"])
class Auth(OAuth):
    def get_auth(self, info, ident, session, state):
        email = info.email or ''
        if info.email_verified and email.split('@')[-1]=='fewsats.com':
            # Ensure user exists and set current user context
            db.ensure_user(info.sub, info.email, info.name, info.picture)
            return RedirectResponse('/', status_code=303)

hdrs = (
    Theme.blue.headers(),
    Link(rel='stylesheet', href='/static/css/style.css', type='text/css'),
    # Script("htmx.logAll();") # debug HTMX events

)


app = FastHTML(hdrs=hdrs)
rt = app.route

# Mount fixed "static/" folder under /static
#    → Serves files like /static/img/logo.png or /static/css/style.css :contentReference[oaicite:12]{index=12}.
app.static_route_exts(prefix='/static', static_path='static', exts='static')

# Mount user-uploads folder under /files
app.static_route_exts(prefix='/files', static_path='data/files', exts='static')

# Skip routes that don't need authentication (otherwise they'll return a 303 redirect)
skip = ('/login', '/logout', '/redirect', '/static/.*/.*', '/files/.*/.*', '/forward/.*')
oauth = Auth(app, cli, skip=skip)


data_dir = Path("data/files")

def UserMenu(email: str): return DivHStacked(P(email), A("Logout", href="/logout"))

def ByFewsats(): 
    return DivHStacked(
            P("by ", cls=[TextPresets.muted_sm, "mr-0"]),
            A(Img(src="https://icons-8e9.pages.dev/Black%20logo%20-%20no%20background.png", width=100),
                href="https://fewsats.com", target="_blank")
        )

def MainLogo():
    return DivVStacked(
            H1('Forward X402', cls="text-center pb-4"),
            ByFewsats(),
        )

@rt('/login')
def login(req): 
    return (
        Title("Forward X402 - Login"),
        Favicon("https://icons-8e9.pages.dev/favicon-black.svg", "https://icons-8e9.pages.dev/favicon.svg"),
        DivVStacked(
            MainLogo(),
            cls="pt-[20vh]",
        ),
        DivVStacked(
            P("Forget spammy emails with low signal. If someone really needs your atttention let them pay for it.", cls=TextPresets.muted_sm + " text-center"),
            A(Button("Log in with Google"), href=oauth.login_link(req), cls='mt-4'),
            cls="p-8",
        )
    )

@rt('/logout')
def logout(session):
    session.pop('auth', None)
    return RedirectResponse('/login', status_code=303)

def NavBar(user):
    return Div(
        DivHStacked(
            A(H1('Forward X402'),  href="/"),
            ByFewsats(),
        ),
        UserMenu(user.email),
        cls="header-container"
    )

@rt
def index(auth):
    user = db.get_user(auth)
    endpoints = db.list_endpoints_by_user(auth)
    
    return (Title("Forward X402 - Dashboard"),
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
async def forward_endpoint(short_url: str, request: Request):
    endpoint = db.get_endpoint_by_short_url(short_url)
    if not endpoint: return
    
    # Get payment requirements
    payment_data = await get_payment_requirements(endpoint, str(request.url).replace('/forward/', '/forward/'))
    
    curl_example = f"""curl -X POST {SERVER_URL}/forward/{short_url} \\
  -H "Content-Type: application/json" \\
  -H "X-PAYMENT: YOUR_PAYMENT_HEADER" \\
  -d '{{
    "email": "your@email.com",
    "subject": "Your Subject Here", 
    "message": "Your message content here"
  }}'"""
    
    return (
        Title(f"Forward X402 - {endpoint.label or 'Email Endpoint'}"),
        Favicon("https://icons-8e9.pages.dev/favicon-black.svg", "https://icons-8e9.pages.dev/favicon.svg"),
        Script(src='/static/js/wallet-reown-bundle.umd.js'),
        Link(rel='stylesheet', href='/static/css/wallet.css', type='text/css'),
        Script(src='/static/js/forward-payment.js'),
        DivVStacked(
            Container(
                DivHStacked(
                    A(H1('Forward X402'),  href="/", cls="mr-4"),
                    ByFewsats(),
                    cls="justify-center mb-8"
                ),
                Card(
                    H3("Send Email to `" + endpoint.label + "`", cls="text-lg font-semibold mb-4"),
                    P(f"Price: ${endpoint.base_price:.6f} USDC", cls="text-gray-700 mb-6"),
                    Form(
                        Input(placeholder="Your email", name="email", required=True, value='post@example.com', cls="w-full border border-gray-300 p-2 mb-4"),
                        Input(placeholder="Subject", name="subject", required=True, value='Test Subject', cls="w-full border border-gray-300 p-2 mb-4"),
                        Textarea('Test Message', placeholder="Message", name="message", required=True, cls="w-full border border-gray-300 p-2 mb-4 min-h-[120px]"),
                        Input(placeholder="X402 Payment Header", name="x402_header", required=True, value='test', cls="w-full border border-gray-300 p-2 mb-4"),
                    ),
                    Button("Connect Wallet", cls="wallet-connect btn btn-primary w-full p-2 mb-4"),
                    Button("Pay", cls="wallet-pay btn btn-success w-full p-2", data_payment=payment_data),
                ),
                Card(
                    Details(
                        Summary("Or use cURL:"),
                        Pre(Code(curl_example, cls="language-bash p-4")),
                    ),
                ),
            ),
        )
    )

async def get_payment_requirements(endpoint, request_url):
    """Get X402 payment requirements for an endpoint"""
    facilitator_config = x402.create_x402_facilitator_config()
    amount = Decimal(str(endpoint.base_price))
    
    response = await x402.payment_middleware(
        url=request_url,
        x_payment=None,  # No payment header to get requirements
        user_agent="",
        accept_header="application/json",
        amount=amount,
        address=os.environ.get("X402_PAYMENT_ADDRESS", ""),
        facilitator_config=facilitator_config,
        description=f"Send email to {endpoint.label}",
        mime_type="application/json",
        max_timeout_seconds=int(os.environ.get("X402_MAX_TIMEOUT_SECONDS", "300")),
        testnet=os.environ.get("ENV", "dev") == "dev",
        resource=f"/forward/{endpoint.short_url}"
    )
    
    return json.dumps(json.loads(response.body.decode())['accepts'][0])


async def parse_payload(request):
    body = await request.json()
    return body.get("email"), body.get("subject"), body.get("message"), request.headers.get("X-PAYMENT")

@app.post("/forward/{short_url}")
async def forward_payment(short_url: str, request: Request):
    endpoint = db.get_endpoint_by_short_url(short_url)
    db.update_hit_count(endpoint.id)

    if not endpoint: return JSONResponse(status_code=404, content={"error": "Endpoint not found"})
    
    sender_email, subject, message, x_payment = await parse_payload(request)
    if not all([sender_email, subject, message]): return JSONResponse(status_code=400, content={"error": "Missing required fields"})

    # Process payment
    facilitator_config = x402.create_x402_facilitator_config()
    amount = Decimal(str(endpoint.base_price))

    response = await x402.payment_middleware(
        url=str(request.url),
        x_payment=x_payment,
        user_agent=request.headers.get("User-Agent", ""),
        accept_header=request.headers.get("Accept", ""),
        amount=amount,
        address=os.environ.get("X402_PAYMENT_ADDRESS", ""),
        facilitator_config=facilitator_config,
        description=f"Send email to {endpoint.label}",
        mime_type="application/json",
        max_timeout_seconds=int(os.environ.get("X402_MAX_TIMEOUT_SECONDS", "300")),
        testnet=os.environ.get("ENV", "dev") == "dev",
        resource=f"/forward/{short_url}"
    )
        
    if response.status_code >= 400: return response
    
    # Send email via Resend
    try:
        params = {
            "from": "noreply@fewsats.com",
            "to": [endpoint.email],
            "subject": f"[Paid Email] {subject}",
            "html": f"<div><p><strong>From:</strong> {sender_email}</p><p><strong>Message:</strong></p><div>{message.replace(chr(10), '<br>')}</div></div>",
            "reply_to": sender_email
        }
        
        email_result = resend.Emails.send(params)
        logger.info(f"Email sent successfully via Resend: {email_result}")
            
        return JSONResponse(status_code=200,
            content={ "success": True,  "message": "Email sent successfully" },
        )
    except Exception as e:
        logger.error(f"Failed to send email via Resend: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to send email"})

serve()