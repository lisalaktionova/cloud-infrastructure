from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse, parse_qs

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/status':
            query = parse_qs(parsed.query)
            order_id = query.get('order_id', [''])[0]
            statuses = {
                '12345': {'status': 'in_transit', 'expected_delivery': '2026-10-18'},
                '67890': {'status': 'delivered', 'expected_delivery': '2026-10-16'}
            }
            response = statuses.get(order_id, {'status': 'unknown', 'expected_delivery': None})
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), Handler)
    print('Mock logistics service running on port 8080')
    server.serve_forever()