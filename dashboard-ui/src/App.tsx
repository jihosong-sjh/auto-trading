/**
 * Main Dashboard App component
 */

import { useDashboardWebSocket } from './hooks/useWebSocket';
import { ConnectionStatus } from './components/ConnectionStatus';
import { PendingOrders } from './components/PendingOrders';
import { PortfolioSummary } from './components/PortfolioSummary';
import { PositionTable } from './components/PositionTable';
import { TradeHistory } from './components/TradeHistory';

function App() {
  const { positions, portfolio, trades, pendingOrders, connectionStatus } = useDashboardWebSocket();

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="dashboard-header">
        <div className="max-w-7xl mx-auto px-4 py-5 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-gradient-to-br from-amber-400 to-amber-600 rounded-lg flex items-center justify-center shadow-lg">
                <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
              </div>
              <div>
                <h1 className="dashboard-title text-2xl sm:text-3xl">
                  키움증권 자동매매
                </h1>
                <p className="text-sm text-slate-400 mt-0.5">실시간 포트폴리오 대시보드</p>
              </div>
            </div>
            <ConnectionStatus status={connectionStatus} />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        <div className="space-y-8">
          {/* Portfolio Summary */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-1.5 h-6 bg-amber-500 rounded-full"></div>
              <h2 className="text-lg font-semibold text-slate-800">자산 현황</h2>
            </div>
            <PortfolioSummary portfolio={portfolio} />
          </section>

          {/* Pending Orders */}
          <section>
            <PendingOrders orders={pendingOrders} />
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
      <footer className="dashboard-footer mt-12">
        <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
          <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
            <p className="text-sm text-slate-500">
              키움증권 자동매매 대시보드 v1.0
            </p>
            <p className="text-xs text-slate-400">
              실시간 데이터 연동 | WebSocket
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
