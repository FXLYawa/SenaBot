import { isServerMessage, type ClientMessage, type ServerMessage } from "../types/protocol";
export type ConnectionStatus = "connecting"|"connected"|"waiting"|"reconnecting"|"disconnected"|"occupied";
export interface SocketEvents { onMessage(message: ServerMessage): void; onStatus(status: ConnectionStatus): void; onError(message: string): void }
export interface SocketOptions extends SocketEvents { url: string; autoReconnect: boolean; reconnectDelay?: number }
export class DesktopSocket {
  private socket: WebSocket | null = null; private timer: number | null = null; private stopped = false; private hasConnected = false;
  constructor(private options: SocketOptions) {}
  connect() {
    this.stopped=false; this.clearTimer(); this.options.onStatus(this.hasConnected ? "reconnecting" : "connecting");
    let socket: WebSocket;
    try { socket = new WebSocket(this.options.url); } catch { this.options.onStatus("disconnected"); this.options.onError("服务地址无效。请在设置中检查地址后重新连接"); return; }
    this.socket=socket;
    socket.addEventListener("open",()=>{ if(this.socket!==socket)return; this.hasConnected=true; this.options.onStatus("connected"); });
    socket.addEventListener("message",event=>{ try { const payload: unknown=JSON.parse(String(event.data)); if(!isServerMessage(payload)) throw new Error(); this.options.onMessage(payload); } catch { this.options.onError("收到无法识别的消息。请检查核心服务版本"); } });
    socket.addEventListener("error",()=>this.options.onError("无法连接本地服务。请确认 SenaBot 核心已启动"));
    socket.addEventListener("close",event=>{ if(this.socket===socket)this.socket=null; if(this.stopped)return; if(event.code===1013){this.stopped=true;this.options.onStatus("occupied");this.options.onError("另一个 Desktop 页面正在使用连接。请先关闭它");return;} if(this.options.autoReconnect){this.options.onStatus("reconnecting");this.timer=window.setTimeout(()=>this.connect(),this.options.reconnectDelay??1500);}else this.options.onStatus("disconnected"); });
  }
  send(text: string) { if(this.socket?.readyState!==WebSocket.OPEN) throw new Error("本地服务尚未连接"); const messageId=crypto.randomUUID(); const frame:ClientMessage={type:"message",message_id:messageId,text}; this.socket.send(JSON.stringify(frame)); return messageId; }
  disconnect(){this.stopped=true;this.clearTimer();this.socket?.close();this.socket=null;}
  private clearTimer(){if(this.timer!==null){window.clearTimeout(this.timer);this.timer=null;}}
}
