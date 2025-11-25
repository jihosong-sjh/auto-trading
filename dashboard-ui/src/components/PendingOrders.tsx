/**
 * Pending Orders component - shows orders in progress
 */

import type { PendingOrder } from '../types/trading';
import { formatKRW, formatNumber } from '../types/trading';

interface PendingOrdersProps {
  orders: PendingOrder[];
}

function getStatusLabel(status: string): string {
  const statusMap: Record<string, string> = {
    PENDING: '대기',
    SUBMITTED: '접수',
    PARTIALLY_FILLED: '부분체결',
    FILLED: '체결완료',
    CANCELLED: '취소',
    REJECTED: '거부',
    FAILED: '실패',
  };
  return statusMap[status] || status;
}

function getStatusStyle(status: string): string {
  const styleMap: Record<string, string> = {
    PENDING: 'bg-slate-100 text-slate-600',
    SUBMITTED: 'bg-blue-50 text-blue-600',
    PARTIALLY_FILLED: 'bg-amber-50 text-amber-600',
    FILLED: 'bg-emerald-50 text-emerald-600',
    CANCELLED: 'bg-slate-100 text-slate-500',
    REJECTED: 'bg-red-50 text-red-600',
    FAILED: 'bg-red-50 text-red-600',
  };
  return styleMap[status] || 'bg-slate-100 text-slate-600';
}

export function PendingOrders({ orders }: PendingOrdersProps) {
  if (orders.length === 0) {
    return (
      <div className="section-card section-pending">
        <div className="section-header">
          <div className="section-header-icon"></div>
          <h2 className="section-title">진행 중인 주문</h2>
        </div>
        <div className="empty-state">
          <svg className="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <p className="text-slate-500">진행 중인 주문이 없습니다</p>
        </div>
      </div>
    );
  }

  return (
    <div className="section-card section-pending">
      <div className="section-header">
        <div className="section-header-icon"></div>
        <h2 className="section-title">진행 중인 주문</h2>
        <span className="section-count">{orders.length}건</span>
      </div>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th className="text-left">종목</th>
              <th className="text-center">유형</th>
              <th className="text-right">주문가</th>
              <th className="text-right">수량</th>
              <th className="text-right">체결</th>
              <th className="text-center">상태</th>
              <th className="text-left">전략</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => {
              const isBuy = order.order_type === 'BUY';
              const fillRate = parseFloat(order.fill_rate);

              return (
                <tr key={order.order_id}>
                  <td className="whitespace-nowrap">
                    <div className="font-semibold text-slate-900">
                      {order.stock_name || order.stock_code}
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {order.stock_code}
                    </div>
                  </td>
                  <td className="whitespace-nowrap text-center">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-sm font-medium ${
                      isBuy ? 'bg-red-50 text-profit' : 'bg-blue-50 text-loss'
                    }`}>
                      {isBuy ? '매수' : '매도'}
                    </span>
                  </td>
                  <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                    {order.price_type === 'MARKET'
                      ? '시장가'
                      : order.limit_price
                        ? formatKRW(order.limit_price)
                        : '-'
                    }
                  </td>
                  <td className="whitespace-nowrap text-right text-slate-700 number-currency">
                    {formatNumber(order.quantity)}
                  </td>
                  <td className="whitespace-nowrap text-right">
                    <div className="text-slate-700 number-currency">
                      {formatNumber(order.filled_quantity)} / {formatNumber(order.quantity)}
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {fillRate.toFixed(1)}%
                    </div>
                  </td>
                  <td className="whitespace-nowrap text-center">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-sm font-medium ${getStatusStyle(order.status)}`}>
                      {getStatusLabel(order.status)}
                    </span>
                  </td>
                  <td className="whitespace-nowrap text-slate-500">
                    {order.strategy_name || '-'}
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
