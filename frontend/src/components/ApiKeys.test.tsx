import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiKeys } from "./ApiKeys";
afterEach(() => { cleanup(); delete window.senaDesktop; });
it("keeps saved secrets hidden and sends replacement keys only to the desktop bridge", async () => {
  const status = {running: true, busy: false, message: "后端已启动", modelSaved: true, embeddingSaved: true};
  const saveKeys = vi.fn().mockResolvedValue(status);
  window.senaDesktop = {status: vi.fn().mockResolvedValue(status), saveKeys, restart: vi.fn().mockResolvedValue(status)};
  render(<ApiKeys/>);
  const model = screen.getByLabelText("对话模型 API Key") as HTMLInputElement;
  await waitFor(() => expect(model.placeholder).toBe("已保存，留空保留"));
  expect(model.type).toBe("password"); expect(model.value).toBe("");
  fireEvent.change(model, {target: {value: "replacement-key"}});
  fireEvent.click(screen.getByText("保存密钥并重启后端"));
  await waitFor(() => expect(saveKeys).toHaveBeenCalledWith({model: "replacement-key", embedding: ""}));
  await waitFor(() => expect(model.value).toBe(""));
});
it("explains browser mode without offering an unsafe local key store", () => {
  render(<ApiKeys/>);
  expect(screen.getByText("请在 SenaBot 桌面窗口中配置 API Key。")).toBeTruthy();
  expect(screen.queryByLabelText("对话模型 API Key")).toBeNull();
});
