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

  const getStatusInfo = () => {
    if (connected) {
      return { text: '연결됨', dotClass: 'connected' };
    }
    if (reconnecting) {
      return { text: '재연결 중...', dotClass: 'reconnecting' };
    }
    return { text: '연결 끊김', dotClass: 'disconnected' };
  };

  const { text, dotClass } = getStatusInfo();

  return (
    <div className="connection-status">
      <div className={`connection-dot ${dotClass}`} />
      <span className="text-white text-sm font-medium">{text}</span>
      {lastUpdate && (
        <span className="text-slate-400 text-xs ml-2 hidden sm:inline">
          최근 업데이트: {formatTime(lastUpdate)}
        </span>
      )}
    </div>
  );
}
