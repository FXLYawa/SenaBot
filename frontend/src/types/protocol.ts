export interface ClientMessage { type: "message"; message_id: string; text: string }
export interface ServerMessage { type: "message"; text: string; reply_to: string | null }
export function isServerMessage(value: unknown): value is ServerMessage {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return item.type === "message" && typeof item.text === "string" && (item.reply_to === null || typeof item.reply_to === "string");
}
