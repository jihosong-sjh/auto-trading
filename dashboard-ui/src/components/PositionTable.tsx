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
      <div className="section-card section-position">
        <div className="section-header">
          <div className="section-header-icon"></div>
          <h2 className="section-title">보유 종목</h2>
        </div>
        <div className="empty-state">
          <svg className="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
          <p className="text-slate-500">보유 중인 종목이 없습니다</p>
        </div>
      </div>
    );
  }

  return (
    <div className="section-card section-position">
      <div className="section-header">
        <div className="section-header-icon"></div>
        <h2 className="section-title">보유 종목</h2>
        <span className="section-count">{positions.length}개</span>
      </div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th className="text-left">종목</th>
              <th className="text-right">수량</th>
              <th className="text-right">평균단가</th>
              <th className="text-right">현재가</th>
              <th className="text-right">평가금액</th>
              <th className="text-right">평가손익</th>
              <th className="text-right">수익률</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => {
              const pnl = parseFloat(position.unrealized_pnl);
              const pnlPct = parseFloat(position.unrealized_pnl_pct);
              const isProfit = pnl >= 0;

              return (
                <tr key={position.stock_code}>
                  <td className="whitespace-nowrap">
                    <div className="font-semibold text-slate-900">
                      {position.stock_name || position.stock_code}
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {position.stock_code}
                    </div>
                  </td>
                  <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                    {formatNumber(position.quantity)}
                  </td>
                  <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                    {formatKRW(position.average_buy_price)}
                  </td>
                  <td className="whitespace-nowrap text-right font-semibold text-slate-900 number-currency">
                    {formatKRW(position.current_price)}
                  </td>
                  <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                    {formatKRW(position.evaluation_amount)}
                  </td>
                  <td className={`whitespace-nowrap text-right number-currency ${isProfit ? 'text-profit' : 'text-loss'}`}>
                    {isProfit ? '+' : ''}{formatKRW(position.unrealized_pnl)}
                  </td>
                  <td className={`whitespace-nowrap text-right ${isProfit ? 'text-profit' : 'text-loss'}`}>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-sm ${
                      isProfit ? 'bg-red-50' : 'bg-blue-50'
                    }`}>
                      {isProfit ? '+' : ''}{formatPercent(pnlPct)}
                    </span>
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
