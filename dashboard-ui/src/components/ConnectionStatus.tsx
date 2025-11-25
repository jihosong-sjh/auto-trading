/**
 * Connection status indicator component
 */

import type { ConnectionStatus as ConnectionStatusType } from '../types/trading';

interface Props {
  status: ConnectionStatusType;
}

export function ConnectionStatus({ status }: Props) {
  const { connected, reconnecting, lastUpdate } = status;

  const formatTime = (date: Date | null) => {
    if (!date) return '-';
    return date.toLocaleTimeString('ko-KR');
  };

  return (
    <div className="flex items-center gap-2 text-sm">
      <div
        className={`w-3 h-3 rounded-full ${
          connected
            ? 'bg-green-500'
            : reconnecting
            ? 'bg-yellow-500 animate-pulse'
            : 'bg-red-500'
        }`}
      />
      <span className="text-gray-600">
        {connected ? 'Connected' : reconnecting ? 'Reconnecting...' : 'Disconnected'}
      </span>
      {lastUpdate && (
        <span className="text-gray-400 ml-2">
          Last update: {formatTime(lastUpdate)}
        </span>
      )}
    </div>
  );
}
