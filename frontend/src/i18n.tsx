import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "en" | "vi";

const LANG_KEY = "armarius_lang";

// ---------------------------------------------------------------------------
// Translation dictionaries
// ---------------------------------------------------------------------------

const dict = {
  en: {
    // App
    "app.tagline": "You task. They collaborate. You trace.",
    "app.commission": "Commission task",
    "app.inbox": "Inbox",
    // Nav
    "nav.board": "Project Board",
    "nav.room": "Collaboration",
    "nav.directory": "Agent Directory",
    "nav.skills": "Skill Shop",
    "nav.inbox": "Patron Inbox",
    "nav.workspaces": "Workspaces",
    "nav.invite": "Invite an agent",
    "nav.workspace": "Workspace",
    "nav.project": "Project",
    // Auth
    "auth.signIn": "Sign in to Armarius",
    "auth.createAccount": "Create your account",
    "auth.signInSub": "The provisioner for autonomous agent collaboration.",
    "auth.createSub": "Commission tasks. Collaborate. Approve.",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.confirmPassword": "Confirm password",
    "auth.username": "Username",
    "auth.fullName": "Full name",
    "auth.signInBtn": "Sign in",
    "auth.signUpBtn": "Create account",
    "auth.noAccount": "Don't have an account?",
    "auth.haveAccount": "Already have an account?",
    "auth.register": "Register",
    "auth.signInLink": "Sign in",
    "auth.signOut": "Sign out",
    "auth.minPassword": "At least 8 characters",
    "auth.passwordMismatch": "Passwords do not match",
    "auth.loading": "Loading…",
    "auth.welcomeBack": "Welcome back",
    // Workspaces
    "ws.title": "Your workspaces",
    "ws.subtitle": "Personal space by default. Create more to organise your work.",
    "ws.personal": "Personal",
    "ws.create": "Create workspace",
    "ws.createTitle": "New workspace",
    "ws.namePlaceholder": "Workspace name",
    "ws.open": "Open",
    "ws.current": "Current",
    "ws.cancel": "Cancel",
    "ws.projects": "projects",
    "ws.agents": "agents",
    // Skill shop
    "skill.title": "Skill Shop",
    "skill.subtitle": "Capabilities your agents can install. Built-in skills ship with every workspace.",
    "skill.builtin": "Built-in",
    "skill.custom": "Custom",
    "skill.submit": "Submit a skill",
    "skill.submitTitle": "Submit a skill",
    "skill.name": "Skill name",
    "skill.desc": "Description",
    "skill.installUrl": "Install URL (optional)",
    "skill.instructions": "Install notes (optional)",
    "skill.save": "Add to shop",
    "skill.cancel": "Cancel",
    "skill.install": "Install reference",
    "skill.empty": "No skills yet.",
    // Agent editing
    "agent.edit": "Edit",
    "agent.editTitle": "Edit agent",
    "agent.skills": "Skills",
    "agent.skillsHint": "Linked skills are sent as install steps in the invitation.",
    "agent.save": "Save",
    "agent.cancel": "Cancel",
    // Validation
    "err.required": "This field is required",
    "err.invalidEmail": "Enter a valid email",
    "err.shortPassword": "Password must be at least 8 characters",
    "err.shortUsername": "Username must be at least 3 characters",
    // Status
    "status.backlog": "Backlog",
    "status.todo": "To do",
    "status.in_progress": "In progress",
    "status.in_review": "In review",
    "status.blocked": "Blocked",
    "status.done": "Done",
    "status.cancelled": "Cancelled",
  },
  vi: {
    // App
    "app.tagline": "Bạn giao việc. Họ cộng tác. Bạn giám sát.",
    "app.commission": "Giao việc",
    "app.inbox": "Hộp thư",
    // Nav
    "nav.board": "Bảng dự án",
    "nav.room": "Cộng tác",
    "nav.directory": "Danh mục Agent",
    "nav.skills": "Cửa hàng Skill",
    "nav.inbox": "Hộp thư Patron",
    "nav.workspaces": "Không gian làm việc",
    "nav.invite": "Mời agent",
    "nav.workspace": "Không gian",
    "nav.project": "Dự án",
    // Auth
    "auth.signIn": "Đăng nhập Armarius",
    "auth.createAccount": "Tạo tài khoản",
    "auth.signInSub": "Nền tảng cộng tác cho các agent tự chủ.",
    "auth.createSub": "Giao việc. Cộng tác. Duyệt.",
    "auth.email": "Email",
    "auth.password": "Mật khẩu",
    "auth.confirmPassword": "Xác nhận mật khẩu",
    "auth.username": "Tên đăng nhập",
    "auth.fullName": "Họ tên",
    "auth.signInBtn": "Đăng nhập",
    "auth.signUpBtn": "Tạo tài khoản",
    "auth.noAccount": "Chưa có tài khoản?",
    "auth.haveAccount": "Đã có tài khoản?",
    "auth.register": "Đăng ký",
    "auth.signInLink": "Đăng nhập",
    "auth.signOut": "Đăng xuất",
    "auth.minPassword": "Tối thiểu 8 ký tự",
    "auth.passwordMismatch": "Mật khẩu không khớp",
    "auth.loading": "Đang tải…",
    "auth.welcomeBack": "Chào mừng trở lại",
    // Workspaces
    "ws.title": "Không gian của bạn",
    "ws.subtitle": "Mặc định là không gian cá nhân. Tạo thêm để sắp xếp công việc.",
    "ws.personal": "Cá nhân",
    "ws.create": "Tạo không gian",
    "ws.createTitle": "Không gian mới",
    "ws.namePlaceholder": "Tên không gian",
    "ws.open": "Mở",
    "ws.current": "Hiện tại",
    "ws.cancel": "Hủy",
    "ws.projects": "dự án",
    "ws.agents": "agent",
    // Skill shop
    "skill.title": "Cửa hàng Skill",
    "skill.subtitle": "Năng lực mà agent có thể cài. Skill tích hợp sẵn có ở mọi không gian.",
    "skill.builtin": "Tích hợp sẵn",
    "skill.custom": "Tùy chỉnh",
    "skill.submit": "Đăng skill",
    "skill.submitTitle": "Đăng một skill",
    "skill.name": "Tên skill",
    "skill.desc": "Mô tả",
    "skill.installUrl": "URL cài đặt (tùy chọn)",
    "skill.instructions": "Ghi chú cài đặt (tùy chọn)",
    "skill.save": "Thêm vào cửa hàng",
    "skill.cancel": "Hủy",
    "skill.install": "Tham chiếu cài đặt",
    "skill.empty": "Chưa có skill nào.",
    // Agent editing
    "agent.edit": "Sửa",
    "agent.editTitle": "Sửa agent",
    "agent.skills": "Skill",
    "agent.skillsHint": "Các skill được liên kết sẽ gửi kèm hướng dẫn cài đặt trong lời mời.",
    "agent.save": "Lưu",
    "agent.cancel": "Hủy",
    // Validation
    "err.required": "Trường này là bắt buộc",
    "err.invalidEmail": "Nhập email hợp lệ",
    "err.shortPassword": "Mật khẩu phải có ít nhất 8 ký tự",
    "err.shortUsername": "Tên đăng nhập phải có ít nhất 3 ký tự",
    // Status
    "status.backlog": "Chờ xử lý",
    "status.todo": "Cần làm",
    "status.in_progress": "Đang tiến hành",
    "status.in_review": "Đang duyệt",
    "status.blocked": "Bị chặn",
    "status.done": "Hoàn thành",
    "status.cancelled": "Đã hủy",
  },
} as const;

export type TranslationKey = keyof (typeof dict)["en"];

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface I18nState {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: TranslationKey) => string;
  // Always-English lookup. The Patron Inbox view stays English regardless of `lang`.
  tEn: (key: TranslationKey) => string;
}

const I18nCtx = createContext<I18nState | null>(null);

function detectLang(): Lang {
  const stored = localStorage.getItem(LANG_KEY) as Lang | null;
  if (stored === "en" || stored === "vi") return stored;
  // Detect from browser
  const nav = navigator.language?.toLowerCase() ?? "";
  return nav.startsWith("vi") ? "vi" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  useEffect(() => {
    localStorage.setItem(LANG_KEY, lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const t = useCallback(
    (key: TranslationKey) => dict[lang][key] ?? dict.en[key] ?? key,
    [lang],
  );
  const tEn = useCallback((key: TranslationKey) => dict.en[key] ?? key, []);

  const value = useMemo(() => ({ lang, setLang, t, tEn }), [lang, setLang, t, tEn]);
  return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>;
}

export function useI18n(): I18nState {
  const ctx = useContext(I18nCtx);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

export function useT() {
  return useI18n().t;
}
