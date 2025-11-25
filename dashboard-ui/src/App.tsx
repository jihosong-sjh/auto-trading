/**
 * Main Dashboard App component
 */

import { useDashboardWebSocket } from './hooks/useWebSocket';
import { ConnectionStatus } from './components/ConnectionStatus';
import { PortfolioSummary } from './components/PortfolioSummary';
import { PositionTable } from './components/PositionTable';
import { TradeHistory } from './components/TradeHistory';

function App() {
  const { positions, portfolio, trades, connectionStatus } = useDashboardWebSocket();

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center">
            <h1 className="text-2xl font-bold text-gray-900">
              Trading Dashboard
            </h1>
            <ConnectionStatus status={connectionStatus} />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        <div className="space-y-6">
          {/* Portfolio Summary */}
          <section>
            <PortfolioSummary portfolio={portfolio} />
          </section>

          {/* Positions */}
          <section>
            <PositionTable positions={positions} />
          </section>

          {/* Trade History */}
          <section>
            <TradeHistory trades={trades} />
          </section>
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t mt-8">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm text-gray-500">
            Kiwoom Auto-Trading Dashboard
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;
