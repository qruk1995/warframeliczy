from flask import Flask, render_template, jsonify
from warframe_profit_calc import WarframeProfitCalculator
import threading
import time

app = Flask(__name__)
calculator = WarframeProfitCalculator()

# Global cache for results
latest_results = []
is_calculating = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/scan')
def scan():
    global is_calculating, latest_results
    if is_calculating:
        return jsonify({'status': 'running', 'message': 'Scan already in progress...'})
    
    def run_scan():
        global is_calculating, latest_results
        is_calculating = True
        try:
            print("Scan thread started.", flush=True)
            
            def update_results(partial_results):
                global latest_results
                latest_results = partial_results

            latest_results = calculator.run_scan(progress_callback=update_results)
            print(f"Scan thread finished. Found {len(latest_results)} results.", flush=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in scan thread: {e}", flush=True)
        finally:
            is_calculating = False

    thread = threading.Thread(target=run_scan)
    thread.start()
    
    return jsonify({'status': 'started', 'message': 'Scan started!'})

@app.route('/api/results')
def results():
    return jsonify({
        'status': 'running' if is_calculating else 'idle',
        'results': latest_results
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
