export interface DesktopSettings { socketUrl:string; characterName:string; textSpeed:number; autoReconnect:boolean; sendWithEnter:boolean }
export const defaultSettings: DesktopSettings={socketUrl:"ws://127.0.0.1:8765",characterName:"Sena",textSpeed:28,autoReconnect:true,sendWithEnter:true};
const KEY="senabot.desktop.settings";
export function loadSettings():DesktopSettings{try{const raw=localStorage.getItem(KEY);if(!raw)return defaultSettings;const value=JSON.parse(raw) as Partial<DesktopSettings>;return {...defaultSettings,...value};}catch{return defaultSettings;}}
export function saveSettings(settings:DesktopSettings){localStorage.setItem(KEY,JSON.stringify(settings));}
