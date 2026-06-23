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
    "nav.inbox": "Patron Inbox",
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
    "auth.loading": "Loading…",
    "auth.welcomeBack": "Welcome back",
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
    "nav.inbox": "Hộp thư Patron",
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
    "auth.loading": "Đang tải…",
    "auth.welcomeBack": "Chào mừng trở lại",
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

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
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
