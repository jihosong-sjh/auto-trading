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
    <div className="section-card section-trade">
      <div className="section-header">
        <div className="section-header-icon"></div>
        <h2 className="section-title">오늘의 거래내역</h2>
        {trades.length > 0 && <span className="section-count">{trades.length}건</span>}
      </div>
      {trades.length === 0 ? (
        <div className="empty-state">
          <svg className="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p className="text-slate-500">오늘 체결된 거래가 없습니다</p>
        </div>
      ) : (
        <div className="overflow-x-auto max-h-80">
          <table className="data-table">
            <thead>
              <tr>
                <th className="text-left">체결시간</th>
                <th className="text-center">구분</th>
                <th className="text-left">종목코드</th>
                <th className="text-right">수량</th>
                <th className="text-right">체결가</th>
                <th className="text-right">실현손익</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => {
                const pnl = trade.realized_pnl ? parseFloat(trade.realized_pnl) : null;
                const isBuy = trade.order_type === 'BUY';

                return (
                  <tr key={trade.order_id}>
                    <td className="whitespace-nowrap text-slate-500">
                      {formatTime(trade.filled_at)}
                    </td>
                    <td className="whitespace-nowrap text-center">
                      <span className={`badge ${isBuy ? 'badge-buy' : 'badge-sell'}`}>
                        {isBuy ? '매수' : '매도'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap">
                      <span className="font-medium text-slate-800">
                        {trade.stock_code}
                      </span>
                    </td>
                    <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                      {formatNumber(trade.quantity)}
                    </td>
                    <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                      {formatKRW(trade.filled_price)}
                    </td>
                    <td className={`whitespace-nowrap text-right number-currency ${
                      pnl === null
                        ? 'text-slate-400'
                        : pnl >= 0
                        ? 'text-profit'
                        : 'text-loss'
                    }`}>
                      {pnl !== null ? (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-sm ${
                          pnl >= 0 ? 'bg-red-50' : 'bg-blue-50'
                        }`}>
                          {pnl >= 0 ? '+' : ''}{formatKRW(pnl)}
                        </span>
                      ) : (
                        <span className="text-slate-300">-</span>
                      )}
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
