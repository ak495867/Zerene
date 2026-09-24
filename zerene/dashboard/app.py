"""
Real-Time Interactive Web Dashboard Studio for ZERENE.
Zero external dependencies (pure Python http.server + JSON endpoint).
Serves real-time L2 order book ladders, trade tape, CVD, and shock controls.
"""

import http.server
import socketserver
import json
import threading
import time
from typing import Optional
from zerene.exchange.venue import ExchangeVenue
from zerene.simulator.market_sim import MarketSimulator


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP Request Handler providing REST JSON market data API & Web UI."""

    simulator_instance: Optional[MarketSimulator] = None

    def do_GET(self):
        if self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            sim = DashboardHandler.simulator_instance
            if not sim:
                self.wfile.write(
                    json.dumps({"error": "No simulator attached"}).encode()
                )
                return

            engine = sim.exchange.engines.get("BTC-USD")
            if not engine:
                self.wfile.write(json.dumps({"error": "No BTC-USD engine"}).encode())
                return

            bids_depth, asks_depth = engine.order_book.get_depth(10)
            trades_recent = [
                {
                    "id": t.trade_id,
                    "price": t.price,
                    "qty": t.quantity,
                    "side": t.aggressor_side.value,
                    "ts": t.timestamp,
                }
                for t in list(engine.trade_history)[-20:]
            ]

            payload = {
                "step": sim.step_count,
                "time": sim.current_time,
                "session": sim.session.value,
                "regime": sim.regime.value,
                "symbol": "BTC-USD",
                "mid": engine.order_book.mid_price() or 0.0,
                "spread": engine.order_book.spread() or 0.0,
                "bids": bids_depth,
                "asks": asks_depth,
                "trades": trades_recent,
            }
            self.wfile.write(json.dumps(payload).encode())
        elif self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD_PAGE.encode("utf-8"))
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        if self.path == "/api/shock":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            action = body.get("action")

            sim = DashboardHandler.simulator_instance
            if sim:
                if action == "flash_crash":
                    sim.inject_flash_crash("BTC-USD", 0.10)
                elif action == "news_shock":
                    sim.inject_news_shock("BTC-USD", 0.05)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "action": action}).encode())


HTML_DASHBOARD_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ZERENE ⚡ Real-Time Market Studio</title>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, monospace; margin: 0; padding: 20px; }
        h1 { color: #38bdf8; display: flex; align-items: center; gap: 10px; }
        .badge { background: #0284c7; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }
        .card { background: #1e293b; border-radius: 10px; padding: 20px; border: 1px solid #334155; }
        .book-table { width: 100%; border-collapse: collapse; font-family: monospace; }
        .book-table th, .book-table td { padding: 6px 12px; text-align: right; }
        .bid-row { color: #4ade80; }
        .ask-row { color: #f87171; }
        .tape-row { font-size: 0.85rem; border-bottom: 1px solid #334155; }
        button { background: #2563eb; color: white; border: none; padding: 10px 18px; border-radius: 6px; font-weight: bold; cursor: pointer; }
        button:hover { background: #1d4ed8; }
        .btn-danger { background: #dc2626; }
        .btn-danger:hover { background: #b91c1c; }
    </style>
</head>
<body>
    <h1>ZERENE ⚡ Real-Time L2 Market Studio <span class="badge" id="session-badge">CONTINUOUS</span></h1>
    <div style="margin-bottom: 15px; display: flex; gap: 10px;">
        <button onclick="triggerShock('flash_crash')" class="btn-danger">⚡ Inject Flash Crash (-10%)</button>
        <button onclick="triggerShock('news_shock')">📰 Inject News Shock (+5%)</button>
    </div>

    <div class="grid">
        <div class="card">
            <h3>📈 Order Book Ladder (BTC-USD)</h3>
            <div style="font-size: 1.1rem; margin-bottom: 10px;">
                Mid Price: <strong id="mid-price" style="color:#38bdf8;">--</strong> | 
                Spread: <strong id="spread">--</strong>
            </div>
            <table class="book-table">
                <thead>
                    <tr><th>Side</th><th>Price ($)</th><th>Volume</th></tr>
                </thead>
                <tbody id="book-body">
                    <tr><td colspan="3">Connecting to ZERENE simulation stream...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="card">
            <h3>⚡ Time & Sales (Live Tape)</h3>
            <div id="tape-body" style="height: 350px; overflow-y: auto;">
                <div style="color: #94a3b8;">Waiting for trades...</div>
            </div>
        </div>
    </div>

    <script>
        async function fetchMarketData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                
                document.getElementById('mid-price').innerText = data.mid ? data.mid.toFixed(2) : '--';
                document.getElementById('spread').innerText = data.spread ? data.spread.toFixed(2) : '--';
                document.getElementById('session-badge').innerText = data.session || 'CONTINUOUS';

                let html = '';
                if (data.asks) {
                    [...data.asks].reverse().forEach(a => {
                        html += `<tr class="ask-row"><td>ASK</td><td>${a[0].toFixed(2)}</td><td>${a[1].toFixed(2)}</td></tr>`;
                    });
                }
                if (data.bids) {
                    data.bids.forEach(b => {
                        html += `<tr class="bid-row"><td>BID</td><td>${b[0].toFixed(2)}</td><td>${b[1].toFixed(2)}</td></tr>`;
                    });
                }
                document.getElementById('book-body').innerHTML = html;

                if (data.trades) {
                    let tapeHtml = '';
                    [...data.trades].reverse().forEach(t => {
                        const color = t.side === 'BUY' ? '#4ade80' : '#f87171';
                        tapeHtml += `<div class="tape-row" style="color:${color};">
                            [${t.ts.toFixed(1)}s] ${t.side} ${t.qty.toFixed(2)} @ $${t.price.toFixed(2)}
                        </div>`;
                    });
                    document.getElementById('tape-body').innerHTML = tapeHtml;
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function triggerShock(action) {
            await fetch('/api/shock', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action: action})
            });
        }

        setInterval(fetchMarketData, 500);
        fetchMarketData();
    </script>
</body>
</html>
"""


def start_dashboard_server(
    simulator: MarketSimulator, port: int = 8080, run_in_background: bool = True
) -> socketserver.TCPServer:
    """Launches the ZERENE Dashboard Studio server."""
    DashboardHandler.simulator_instance = simulator
    server = socketserver.TCPServer(("", port), DashboardHandler)
    if run_in_background:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        print(f"[+] ZERENE Dashboard Studio running at http://localhost:{port}/")
    return server
