import type { ConnectionStatus } from "../services/desktopSocket";

const labels: Record<ConnectionStatus, string> = {
  connecting: "正在连接",
  connected: "在线",
  waiting: "正在回应",
  reconnecting: "正在重连",
  disconnected: "离线",
  occupied: "连接占用",
};

export function CharacterStage({ status }: { status: ConnectionStatus }) {
  return (
    <section className="stage" aria-label="角色舞台">
      <div className="portrait">
        <img
          className="characterImage"
          src="/characters/sena/sena-neutral.png"
          alt="Sena 的角色立绘"
        />
      </div>
      <div className="connection" role="status" aria-live="polite">
        <span className={`statusDot status-${status}`} />
        {labels[status]}
      </div>
    </section>
  );
}
