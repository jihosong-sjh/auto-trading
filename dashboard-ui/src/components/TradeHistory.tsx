/**
 * Trade history component
 */

import type { Trade } from '../types/trading';
import { formatKRW, formatNumber } from '../types/trading';

interface Props {
  trades: Trade[];
}

export function TradeHistory({ trades }: Props) {
  const formatTime = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString('ko-KR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="px-4 py-3 border-b">
        <h2 className="text-lg font-semibold">Today's Trades ({trades.length})</h2>
      </div>
      {trades.length === 0 ? (
        <div className="p-8 text-center text-gray-500">
          No trades today
        </div>
      ) : (
        <div className="overflow-x-auto max-h-64">
          <table className="w-full">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Time
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Stock
                </th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Qty
                </th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Price
                </th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  P&L
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {trades.map((trade) => {
                const pnl = trade.realized_pnl ? parseFloat(trade.realized_pnl) : null;
                const isBuy = trade.order_type === 'BUY';

                return (
                  <tr key={trade.order_id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-500">
                      {formatTime(trade.filled_at)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <span
                        className={`px-2 py-1 text-xs font-medium rounded ${
                          isBuy
                            ? 'bg-red-100 text-red-800'
                            : 'bg-blue-100 text-blue-800'
                        }`}
                      >
                        {trade.order_type}
                      </span>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900">
                        {trade.stock_code}
                      </div>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-right text-sm text-gray-900">
                      {formatNumber(trade.quantity)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-right text-sm text-gray-900">
                      {formatKRW(trade.filled_price)}
                    </td>
                    <td
                      className={`px-4 py-2 whitespace-nowrap text-right text-sm font-medium ${
                        pnl === null
                          ? 'text-gray-400'
                          : pnl >= 0
                          ? 'text-green-600'
                          : 'text-red-600'
                      }`}
                    >
                      {pnl !== null ? formatKRW(pnl) : '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
