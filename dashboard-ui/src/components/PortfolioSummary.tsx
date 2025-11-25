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
  icon: React.ReactNode;
  accentColor: string;
}

function SummaryCard({ title, value, subtitle, valueColor = 'neutral', icon, accentColor }: CardProps) {
  const colorClass =
    valueColor === 'profit'
      ? 'text-profit'
      : valueColor === 'loss'
      ? 'text-loss'
      : 'text-slate-900';

  return (
    <div className="summary-card relative overflow-hidden">
      <div className={`absolute top-0 left-0 w-1 h-full ${accentColor}`}></div>
      <div className="flex items-start justify-between">
        <div className="flex-1 pl-3">
          <p className="summary-card-label">{title}</p>
          <p className={`summary-card-value number-currency ${colorClass}`}>{value}</p>
          {subtitle && <p className="summary-card-subtitle">{subtitle}</p>}
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${accentColor} bg-opacity-10`}>
          {icon}
        </div>
      </div>
    </div>
  );
}

export function PortfolioSummary({ portfolio }: Props) {
  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="summary-card">
            <div className="h-4 skeleton w-24 mb-3" />
            <div className="h-8 skeleton w-32 mb-2" />
            <div className="h-3 skeleton w-16" />
          </div>
        ))}
      </div>
    );
  }

  const totalUnrealizedPnl = parseFloat(portfolio.total_unrealized_pnl);
  const dailyRealizedPnl = parseFloat(portfolio.daily_realized_pnl);
  const totalReturnPct = parseFloat(portfolio.total_return_pct);

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <SummaryCard
        title="총 자산"
        value={formatKRW(portfolio.total_asset_value)}
        accentColor="bg-amber-500"
        icon={
          <svg className="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        }
      />
      <SummaryCard
        title="평가 손익"
        value={formatKRW(portfolio.total_unrealized_pnl)}
        subtitle={formatPercent(totalReturnPct)}
        valueColor={totalUnrealizedPnl >= 0 ? 'profit' : 'loss'}
        accentColor={totalUnrealizedPnl >= 0 ? 'bg-red-500' : 'bg-blue-500'}
        icon={
          <svg className={`w-5 h-5 ${totalUnrealizedPnl >= 0 ? 'text-red-600' : 'text-blue-600'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {totalUnrealizedPnl >= 0 ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
            )}
          </svg>
        }
      />
      <SummaryCard
        title="오늘 실현 손익"
        value={formatKRW(portfolio.daily_realized_pnl)}
        valueColor={dailyRealizedPnl >= 0 ? 'profit' : 'loss'}
        accentColor={dailyRealizedPnl >= 0 ? 'bg-red-500' : 'bg-blue-500'}
        icon={
          <svg className={`w-5 h-5 ${dailyRealizedPnl >= 0 ? 'text-red-600' : 'text-blue-600'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        }
      />
      <SummaryCard
        title="예수금"
        value={formatKRW(portfolio.cash_balance)}
        subtitle={`보유 종목 ${portfolio.position_count}개`}
        accentColor="bg-emerald-500"
        icon={
          <svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
          </svg>
        }
      />
    </div>
  );
}
