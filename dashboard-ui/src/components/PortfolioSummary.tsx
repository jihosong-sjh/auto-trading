/**
 * Portfolio summary cards component
 */

import type { Portfolio } from '../types/trading';
import { formatKRW, formatPercent } from '../types/trading';

interface Props {
  portfolio: Portfolio | null;
}

interface CardProps {
  title: string;
  value: string;
  subtitle?: string;
  valueColor?: 'profit' | 'loss' | 'neutral';
}

function SummaryCard({ title, value, subtitle, valueColor = 'neutral' }: CardProps) {
  const colorClass =
    valueColor === 'profit'
      ? 'text-green-600'
      : valueColor === 'loss'
      ? 'text-red-600'
      : 'text-gray-900';

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <p className="text-sm text-gray-500 mb-1">{title}</p>
      <p className={`text-2xl font-bold ${colorClass}`}>{value}</p>
      {subtitle && <p className="text-sm text-gray-400 mt-1">{subtitle}</p>}
    </div>
  );
}

export function PortfolioSummary({ portfolio }: Props) {
  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-white rounded-lg shadow p-4 animate-pulse">
            <div className="h-4 bg-gray-200 rounded w-24 mb-2" />
            <div className="h-8 bg-gray-200 rounded w-32" />
          </div>
        ))}
      </div>
    );
  }

  const totalUnrealizedPnl = parseFloat(portfolio.total_unrealized_pnl);
  const dailyRealizedPnl = parseFloat(portfolio.daily_realized_pnl);
  const totalReturnPct = parseFloat(portfolio.total_return_pct);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <SummaryCard
        title="Total Asset Value"
        value={formatKRW(portfolio.total_asset_value)}
      />
      <SummaryCard
        title="Unrealized P&L"
        value={formatKRW(portfolio.total_unrealized_pnl)}
        subtitle={formatPercent(totalReturnPct)}
        valueColor={totalUnrealizedPnl >= 0 ? 'profit' : 'loss'}
      />
      <SummaryCard
        title="Daily Realized P&L"
        value={formatKRW(portfolio.daily_realized_pnl)}
        valueColor={dailyRealizedPnl >= 0 ? 'profit' : 'loss'}
      />
      <SummaryCard
        title="Cash Balance"
        value={formatKRW(portfolio.cash_balance)}
        subtitle={`${portfolio.position_count} positions`}
      />
    </div>
  );
}
