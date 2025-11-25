/**
 * Position table component with real-time updates
 */

import type { Position } from '../types/trading';
import { formatKRW, formatPercent, formatNumber } from '../types/trading';

interface Props {
  positions: Position[];
}

export function PositionTable({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow">
        <div className="px-4 py-3 border-b">
          <h2 className="text-lg font-semibold">Positions</h2>
        </div>
        <div className="p-8 text-center text-gray-500">
          No positions
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="px-4 py-3 border-b">
        <h2 className="text-lg font-semibold">Positions ({positions.length})</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Stock
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Quantity
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Avg Price
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Current Price
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Evaluation
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                P&L
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Return
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {positions.map((position) => {
              const pnl = parseFloat(position.unrealized_pnl);
              const pnlPct = parseFloat(position.unrealized_pnl_pct);
              const isProfit = pnl >= 0;

              return (
                <tr key={position.stock_code} className="hover:bg-gray-50">
                  <td className="px-4 py-4 whitespace-nowrap">
                    <div className="font-medium text-gray-900">
                      {position.stock_code}
                    </div>
                    <div className="text-sm text-gray-500">
                      {position.stock_name || '-'}
                    </div>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-right text-gray-900">
                    {formatNumber(position.quantity)}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-right text-gray-900">
                    {formatKRW(position.average_buy_price)}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-right font-medium text-gray-900">
                    {formatKRW(position.current_price)}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-right text-gray-900">
                    {formatKRW(position.evaluation_amount)}
                  </td>
                  <td
                    className={`px-4 py-4 whitespace-nowrap text-right font-medium ${
                      isProfit ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {formatKRW(position.unrealized_pnl)}
                  </td>
                  <td
                    className={`px-4 py-4 whitespace-nowrap text-right font-medium ${
                      isProfit ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {formatPercent(pnlPct)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
