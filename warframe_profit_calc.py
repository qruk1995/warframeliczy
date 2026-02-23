import requests
import time
import datetime
from threading import Lock

API_BASE_URL = "https://api.warframe.market/v2"
ITEMS_URL = f"{API_BASE_URL}/items"

# Rate Limit Config
REQUEST_DELAY = 0.34  # ~3 requests per second

class WarframeMarketAPI:
    def __init__(self):
        self.session = requests.Session()
        # Dodajemy nagłówki, by udawać normalną przeglądarkę i uniknąć blokady bota
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Platform': 'pc',
            'Language': 'en'
        })
        self.last_request_time = 0
        self.lock = Lock()
        self.item_cache = {} # Cache for item details (static data)

    def _get(self, url):
        with self.lock:
            elapsed = time.time() - self.last_request_time
            if elapsed < REQUEST_DELAY:
                time.sleep(REQUEST_DELAY - elapsed)
            
            try:
                # print(f"Fetching {url}...", flush=True)
                response = self.session.get(url)
                self.last_request_time = time.time()
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                print(f"Error fetching {url}: {e}")
                return None

    def get_all_items(self):
        # This returns the lightweight list
        data = self._get(ITEMS_URL)
        if data:
            return data['data']
        return []

    def get_item_details(self, url_name):
        if url_name in self.item_cache:
            return self.item_cache[url_name]
            
        url = f"{ITEMS_URL}/{url_name}"
        data = self._get(url)
        if data:
            item_data = data['data']
            self.item_cache[url_name] = item_data
            return item_data
        return None

    def get_orders(self, url_name):
        # Orders are volatile, do not cache likely needed fresh
        url = f"{API_BASE_URL}/orders/item/{url_name}"
        data = self._get(url)
        if data:
            return data['data']
        return []

class WarframeProfitCalculator:
    def __init__(self):
        self.api = WarframeMarketAPI()
        self.all_items_map = {} # ID -> Slug
        self.all_items_data = []

    def initialize_items(self):
        if not self.all_items_data:
            print("Initializing items list...", flush=True)
            self.all_items_data = self.api.get_all_items()
            for item in self.all_items_data:
                self.all_items_map[item['id']] = item['slug']
            print(f"Loaded {len(self.all_items_data)} items.", flush=True)

    def get_lowest_sell_price(self, orders):
        # Filter for 'sell' orders from users who are 'ingame' or 'online'
        valid_orders = [
            o for o in orders 
            if o['type'] == 'sell' 
            and o['user']['status'] in ['ingame', 'online']
        ]
        if not valid_orders:
            return float('inf')
        
        # Sort by price ascending
        valid_orders.sort(key=lambda x: x['platinum'])
        return valid_orders[0]['platinum']

    def calculate_set_profit(self, set_item_summary):
        set_slug = set_item_summary['slug']
        
        # 1. Get Set Details (to find parts)
        set_details = self.api.get_item_details(set_slug)
        if not set_details:
            return None

        # Check if it is a set
        if 'setParts' not in set_details:
            return None
            
        # 2. Identify Components
        # setParts is a list of IDs.
        parts_ids = set_details['setParts']
        
        # Filter out the set itself from parts list (sometimes it's included?)
        # Actually usually the Set Item ID is in setParts too.
        # We need to distinguish "The Set" from "The Parts".
        # 'set_root' in v1, 'setRoot' in v2?
        # Checked chroma_prime_set: 'setRoot': True.
        
        # But wait, looking at updated logic:
        # We start with the Set Item.
        # Its parts are in setParts.
        # One of them is the set itself (setRoot=True).
        # The others are components.
        
        components = []
        set_root_item = None
        
        # We need to look up slugs for all IDs
        for pid in parts_ids:
            if pid not in self.all_items_map:
                continue
            p_slug = self.all_items_map[pid]
            
            # Get part details to check if it's the root and get quantity
            p_details = self.api.get_item_details(p_slug)
            if not p_details:
                continue
                
            if p_details.get('setRoot', False):
                set_root_item = p_details
            else:
                components.append(p_details)

        if not set_root_item:
            # Fallback: maybe the item we started with IS the root
            if set_details.get('setRoot', False):
                set_root_item = set_details
        
        if not set_root_item:
            return None

        # 3. Get Price for Set
        set_orders = self.api.get_orders(set_root_item['slug'])
        set_price = self.get_lowest_sell_price(set_orders)
        
        if set_price == float('inf'):
            return None

        # 4. Get Prices for Components
        total_cost = 0
        component_data = []
        
        for comp in components:
            qty = comp.get('quantityInSet', 1)
            # Some items might have quantity 0 or null? Default to 1.
            if not qty: qty = 1
            
            orders = self.api.get_orders(comp['slug'])
            price = self.get_lowest_sell_price(orders)
            
            if price == float('inf'):
                return None # Incomplete set
            
            cost = price * qty
            total_cost += cost
            
            component_data.append({
                'name': comp['i18n']['en']['name'],
                'price': f"{qty}x {price} = {cost}", 
                # or just unit price? Let's show total for that component
                'unit_price': price,
                'qty': qty
            })

        profit = set_price - total_cost
        trades = sum(comp['qty'] for comp in component_data) + 1
        
        return {
            'name': set_root_item['i18n']['en']['name'],
            'set_price': set_price,
            'cost': total_cost,
            'profit': profit,
            'trades': trades,
            'components': component_data
        }

    def run_scan(self, progress_callback=None):
        self.initialize_items()
        
        # Filter for Prime Sets
        target_sets = [
            i for i in self.all_items_data 
            if 'Prime Set' in i.get('i18n', {}).get('en', {}).get('name', '')
        ]
        
        print(f"Found {len(target_sets)} Prime Sets.", flush=True)
        
        results = []
        
        for i, item in enumerate(target_sets):
            print(f"Scanning {i+1}/{len(target_sets)}: {item['slug']}...", flush=True)
            res = self.calculate_set_profit(item)
            if res and res['profit'] > 0:
                results.append(res)
                # Sort incrementally and call protocol
                # Sort by cost ascending
                results.sort(key=lambda x: x['cost'])
                if progress_callback:
                    # Provide a copy to avoid threading concurrency issues during JSON serialization
                    progress_callback(list(results))
                
        return results
