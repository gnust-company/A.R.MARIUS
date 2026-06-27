import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "en" | "vi";

const LANG_KEY = "armarius_lang";

// ---------------------------------------------------------------------------
// Translation dictionaries — single source of truth for ALL visible strings.
// Use {param} placeholders for interpolation, e.g. t("x.count", { n: 3 }).
// ---------------------------------------------------------------------------

const dict = {
  en: {
    // App / chrome
    "app.tagline": "You task. They collaborate. You trace.",
    "app.scriptorium": "Scriptorium",
    "app.loadingScriptorium": "Loading the scriptorium…",
    "app.loading": "Loading…",
    // Nav
    "nav.board": "Project Board",
    "nav.room": "Collaboration",
    "nav.directory": "Agent Directory",
    "nav.skills": "Skill Shop",
    "nav.inbox": "Patron Inbox",
    "nav.workspaces": "Workspaces",
    "nav.back": "← All workspaces",
    "nav.invite": "Invite an agent",
    "nav.workspace": "Workspace",
    "nav.project": "Project",
    "nav.style": "Atelier",
    "nav.profile": "Account",
    // Style playground
    "style.title": "Design Atelier",
    "style.subtitle": "The Scriptorium design system",
    "style.palette": "Palette",
    "style.typography": "Typography",
    "style.components": "Components",
    "style.motion": "Motion",
    "style.bodySample": "Armarius is a scriptorium for agent collaboration — warm parchment, terracotta and gold leaf, classical serifs.",
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
    "auth.failed": "Authentication failed",
    // Profile (the Patron's attribution page)
    "profile.attribution": "Attribution",
    "profile.identity": "Identity",
    "profile.verified": "Verified",
    "profile.inactive": "Inactive",
    "profile.fullName": "Full name",
    "profile.role": "Role",
    "profile.memberSince": "Member since",
    "profile.lastLogin": "Last login",
    "profile.never": "Never",
    "profile.userId": "User id",
    "profile.workshop": "Workshop",
    "profile.preferences": "Preferences",
    "profile.language": "Language",
    "profile.session": "Session",
    "profile.sessionSub": "You're signed in to this scriptorium.",
    // Common
    "common.copy": "Copy",
    "common.done": "Done",
    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.edit": "Edit",
    "common.open": "Open",
    "common.loading": "Loading…",
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
    "ws.project": "project",
    "ws.agents": "agents",
    "ws.agent": "agent",
    "ws.countOne": "1 workspace",
    "ws.count": "{n} workspaces",
    // Skill shop
    "skill.title": "Skill Shop",
    "skill.subtitle": "Capabilities your agents can install. Built-in skills ship with every workspace.",
    "skill.builtin": "Built-in",
    "skill.custom": "Custom",
    "skill.submit": "Submit a skill",
    "skill.submitTitle": "Submit a skill",
    "skill.name": "Skill name",
    "skill.desc": "Description",
    "skill.kind": "Kind",
    "skill.installUrl": "Install URL (optional)",
    "skill.instructions": "Install notes (optional)",
    "skill.install": "Install reference",
    "skill.empty": "No skills yet.",
    "skill.preview": "Preview",
    "skill.previewTitle": "Skill preview",
    "skill.loading": "Loading skill…",
    "skill.noContent": "No previewable content for this skill.",
    "skill.fetchFail": "Could not load the skill file.",
    "skill.count": "{n} skills",
    "skill.sourceUrl": "Skill source URL",
    "skill.sourceUrlHint": "A link to a SKILL.md (GitHub raw or a repo). The agent pulls the skill from here.",
    "skill.sourceUrlPlaceholder": "https://raw.githubusercontent.com/owner/repo/main/my-skill/SKILL.md",
    "skill.fetch": "Fetch & preview",
    "skill.detected": "Detected from the skill",
    "skill.notSkill": "This doesn't look like a SKILL.md — no `name:` in the frontmatter.",
    "skill.fetchFailShort": "Could not fetch that URL.",
    "skill.selectLabel": "Select skills",
    // Skill authoring
    "skill.newSkill": "New skill",
    "skill.newManual": "Write manually",
    "skill.newImport": "Import from GitHub",
    "skill.manualTitle": "New skill",
    "skill.importTitle": "Import a skill",
    "skill.importPlaceholder": "https://github.com/owner/repo/tree/main/skills/my-skill",
    "skill.importHint": "A GitHub folder that contains a SKILL.md. We clone just that folder.",
    "skill.importBtn": "Import",
    "skill.importing": "Importing…",
    "skill.create": "Create",
    "skill.manualHint": "A SKILL.md template is generated — edit it and add files (scripts/, references/…) afterwards.",
    "skill.editor": "Edit skill",
    "skill.files": "Files",
    "skill.addFile": "Add file",
    "skill.newFilePath": "path/to/file (e.g. scripts/run.sh)",
    "skill.deleteFile": "Delete",
    "skill.confirmDelete": "Delete this file?",
    "skill.save": "Save",
    "skill.saved": "Saved.",
    "skill.unsaved": "Unsaved changes",
    // Modal
    "modal.close": "Close",
    // Agent directory / provision / edit
    "agent.directory": "Agent directory",
    "agent.count": "{n} agents",
    "agent.provision": "Provision a Marius",
    "agent.provisionTitle": "Provision a Marius",
    "agent.editTitle": "Edit agent",
    "agent.namePlaceholder": "Name (e.g. Marin)",
    "agent.rolePlaceholder": "Role (e.g. Backend)",
    "agent.skills": "Skills",
    "agent.skillsHint": "Selected skills are sent as install steps in the invitation.",
    "agent.skillsSelected": "{n} selected",
    "agent.skillsEmpty": "No skills in this workspace yet. Add one in the Skill Shop.",
    "agent.adapter": "Adapter",
    "agent.gatewayUrl": "Gateway base_url",
    "agent.gatewayKey": "API_SERVER_KEY (bearer)",
    "agent.createInvite": "Create & invite",
    "agent.copied": "Copied",
    "agent.noSkills": "no linked skills",
    "agent.inviteFor": "Invitation for {name}",
    "agent.inviteSub": "Paste this to your agent so it joins, saves its token, confirms online, and installs its skills.",
    "agent.adapterLabel": "adapter",
    // Board
    "board.commission": "Commission task",
    "board.newTaskPlaceholder": "New task title…",
    "board.tasks": "{n} tasks",
    "board.inProject": "In this project",
    "board.unassigned": "Unassigned",
    "board.title": "Board",
    "board.empty": "—",
    "board.titleLabel": "Title",
    "board.descLabel": "Description (optional)",
    "board.descPlaceholder": "What needs doing? Context, acceptance criteria, links…",
    // Room / collaboration
    "room.collaborationRoom": "Collaboration room",
    "room.backToBoard": "Board",
    "room.loadingTask": "Loading task…",
    "room.notFound": "Task not found.",
    "room.status": "Status",
    "room.assignee": "Assignee",
    "room.unassigned": "— Unassigned —",
    "room.assignWake": "assigning fires an event-wake",
    "room.recordedNext": "Recorded next action",
    "room.dod": "Definition of done",
    "room.dodArtifact": "Published artifact in the shared store",
    "room.artifacts": "Artifacts",
    "room.noneYet": "None yet.",
    "room.thread": "Collaboration thread",
    "room.system": "System",
    "room.patron": "Patron",
    "room.agent": "agent",
    "room.noMessages": "No messages yet.",
    "room.messagePlaceholder": "Message the room — use @Name to wake a specific agent…",
    "room.sendHint": "⌘/Ctrl + Enter to send · @mention wakes",
    "room.send": "Send",
    "room.awaitingReview": "Awaiting your review",
    "room.requestChanges": "Request changes",
    "room.approvePublish": "Approve & publish",
    "room.liveTrace": "Live trace",
    "room.streaming": "● streaming",
    "room.noRuns": "No runs yet. Wake an agent to watch it work.",
    "room.failed": "Failed",
    "room.cannotStatus": "Cannot change status",
    "room.pickAgent": "pick agent",
    "room.wake": "Wake",
    // Patron inbox (bilingual)
    "inbox.title": "Patron inbox",
    "inbox.count": "{n} need you",
    "inbox.subtitle": "Only what needs a human decision: artifacts ready for review, and blocked work.",
    "inbox.empty": "Nothing awaits you. The scriptorium is calm. ✦",
    "inbox.open": "Open",
    "inbox.approve": "Approve",
    "inbox.reviewGroup": "Awaiting your review",
    "inbox.blockedGroup": "Blocked",
    // Validation / errors
    "err.required": "This field is required",
    "err.invalidEmail": "Enter a valid email",
    "err.shortPassword": "Password must be at least 8 characters",
    "err.noWorkspace": "No workspace found.",
    "err.failedLoad": "Failed to load",
    // Task status
    "status.backlog": "Backlog",
    "status.todo": "To do",
    "status.in_progress": "In progress",
    "status.in_review": "In review",
    "status.blocked": "Blocked",
    "status.done": "Done",
    "status.cancelled": "Cancelled",
    // Liveness
    "liveness.online": "Online",
    "liveness.working": "Working",
    "liveness.idle": "Idle",
    "liveness.offline": "Offline",
    "liveness.hung": "Hung",
    // Relative time
    "time.secondsAgo": "{n}s ago",
    "time.minutesAgo": "{n}m ago",
    "time.hoursAgo": "{n}h ago",
    "time.daysAgo": "{n}d ago",
  },
  vi: {
    // App / chrome
    "app.tagline": "Bạn giao việc. Họ cộng tác. Bạn giám sát.",
    "app.scriptorium": "Scriptorium",
    "app.loadingScriptorium": "Đang tải scriptorium…",
    "app.loading": "Đang tải…",
    // Nav
    "nav.board": "Bảng dự án",
    "nav.room": "Cộng tác",
    "nav.directory": "Danh mục Agent",
    "nav.skills": "Cửa hàng Skill",
    "nav.inbox": "Hộp thư Patron",
    "nav.workspaces": "Không gian làm việc",
    "nav.back": "← Tất cả không gian",
    "nav.invite": "Mời agent",
    "nav.workspace": "Không gian",
    "nav.project": "Dự án",
    "nav.style": "Xưởng",
    "nav.profile": "Tài khoản",
    // Style playground
    "style.title": "Xưởng thiết kế",
    "style.subtitle": "Hệ thống thiết kế Scriptorium",
    "style.palette": "Bảng màu",
    "style.typography": "Kiểu chữ",
    "style.components": "Thành phần",
    "style.motion": "Chuyển động",
    "style.bodySample": "Armarius là một scriptorium cho agent cộng tác — giấy parchment ấm, terracotta và vàng hoàng kim, serif cổ điển.",
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
    "auth.failed": "Đăng nhập thất bại",
    // Profile (the Patron's attribution page)
    "profile.attribution": "Bản ghi danh",
    "profile.identity": "Định danh",
    "profile.verified": "Đã xác minh",
    "profile.inactive": "Không hoạt động",
    "profile.fullName": "Họ tên",
    "profile.role": "Vai trò",
    "profile.memberSince": "Thành viên từ",
    "profile.lastLogin": "Đăng nhập cuối",
    "profile.never": "Chưa từng",
    "profile.userId": "Mã người dùng",
    "profile.workshop": "Xưởng",
    "profile.preferences": "Tùy chọn",
    "profile.language": "Ngôn ngữ",
    "profile.session": "Phiên",
    "profile.sessionSub": "Bạn đang đăng nhập vào scriptorium này.",
    // Common
    "common.copy": "Sao chép",
    "common.done": "Xong",
    "common.cancel": "Hủy",
    "common.save": "Lưu",
    "common.edit": "Sửa",
    "common.open": "Mở",
    "common.loading": "Đang tải…",
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
    "ws.project": "dự án",
    "ws.agents": "agent",
    "ws.agent": "agent",
    "ws.countOne": "1 không gian",
    "ws.count": "{n} không gian",
    // Skill shop
    "skill.title": "Cửa hàng Skill",
    "skill.subtitle": "Năng lực mà agent có thể cài. Skill tích hợp sẵn có ở mọi không gian.",
    "skill.builtin": "Tích hợp sẵn",
    "skill.custom": "Tùy chỉnh",
    "skill.submit": "Đăng skill",
    "skill.submitTitle": "Đăng một skill",
    "skill.name": "Tên skill",
    "skill.desc": "Mô tả",
    "skill.kind": "Loại",
    "skill.installUrl": "URL cài đặt (tùy chọn)",
    "skill.instructions": "Ghi chú cài đặt (tùy chọn)",
    "skill.install": "Tham chiếu cài đặt",
    "skill.empty": "Chưa có skill nào.",
    "skill.preview": "Xem trước",
    "skill.previewTitle": "Xem trước skill",
    "skill.loading": "Đang tải skill…",
    "skill.noContent": "Skill này không có nội dung xem trước.",
    "skill.fetchFail": "Không tải được file skill.",
    "skill.count": "{n} skill",
    "skill.sourceUrl": "URL nguồn của skill",
    "skill.sourceUrlHint": "Link tới một SKILL.md (GitHub raw hoặc repo). Agent sẽ kéo skill từ đây.",
    "skill.sourceUrlPlaceholder": "https://raw.githubusercontent.com/owner/repo/main/my-skill/SKILL.md",
    "skill.fetch": "Tải & xem trước",
    "skill.detected": "Phát hiện từ skill",
    "skill.notSkill": "Không giống SKILL.md — không có `name:` ở frontmatter.",
    "skill.fetchFailShort": "Không tải được URL đó.",
    "skill.selectLabel": "Chọn skill",
    // Skill authoring
    "skill.newSkill": "Skill mới",
    "skill.newManual": "Viết tay",
    "skill.newImport": "Nhập từ GitHub",
    "skill.manualTitle": "Skill mới",
    "skill.importTitle": "Nhập một skill",
    "skill.importPlaceholder": "https://github.com/owner/repo/tree/main/skills/my-skill",
    "skill.importHint": "Một thư mục GitHub có chứa SKILL.md. Ta chỉ clone đúng thư mục đó.",
    "skill.importBtn": "Nhập",
    "skill.importing": "Đang nhập…",
    "skill.create": "Tạo",
    "skill.manualHint": "Sẽ tạo một template SKILL.md — bạn sửa và thêm tệp (scripts/, references/…) sau.",
    "skill.editor": "Sửa skill",
    "skill.files": "Tệp",
    "skill.addFile": "Thêm tệp",
    "skill.newFilePath": "đường_dẫn/tệp (vd scripts/run.sh)",
    "skill.deleteFile": "Xóa",
    "skill.confirmDelete": "Xóa tệp này?",
    "skill.save": "Lưu",
    "skill.saved": "Đã lưu.",
    "skill.unsaved": "Chưa lưu thay đổi",
    // Modal
    "modal.close": "Đóng",
    // Agent directory / provision / edit
    "agent.directory": "Danh mục agent",
    "agent.count": "{n} agent",
    "agent.provision": "Khởi tạo Marius",
    "agent.provisionTitle": "Khởi tạo Marius",
    "agent.editTitle": "Sửa agent",
    "agent.namePlaceholder": "Tên (vd Marin)",
    "agent.rolePlaceholder": "Vai trò (vd Backend)",
    "agent.skills": "Skill",
    "agent.skillsHint": "Các skill được chọn sẽ gửi kèm hướng dẫn cài đặt trong lời mời.",
    "agent.skillsSelected": "đã chọn {n}",
    "agent.skillsEmpty": "Không gian này chưa có skill nào. Thêm ở Cửa hàng Skill.",
    "agent.adapter": "Bộ chuyển đổi",
    "agent.gatewayUrl": "Gateway base_url",
    "agent.gatewayKey": "API_SERVER_KEY (bearer)",
    "agent.createInvite": "Tạo & mời",
    "agent.copied": "Đã chép",
    "agent.noSkills": "chưa liên kết skill",
    "agent.inviteFor": "Lời mời cho {name}",
    "agent.inviteSub": "Dán đoạn này cho agent để nó tham gia, lưu token, xác nhận đang online và cài các skill.",
    "agent.adapterLabel": "bộ chuyển đổi",
    // Board
    "board.commission": "Giao việc",
    "board.newTaskPlaceholder": "Tiêu đề công việc mới…",
    "board.tasks": "{n} công việc",
    "board.inProject": "Trong dự án này",
    "board.unassigned": "Chưa giao",
    "board.title": "Bảng",
    "board.empty": "—",
    "board.titleLabel": "Tiêu đề",
    "board.descLabel": "Mô tả (tùy chọn)",
    "board.descPlaceholder": "Cần làm gì? Ngữ cảnh, tiêu chí, link…",
    // Room / collaboration
    "room.collaborationRoom": "Phòng cộng tác",
    "room.backToBoard": "Bảng",
    "room.loadingTask": "Đang tải công việc…",
    "room.notFound": "Không tìm thấy công việc.",
    "room.status": "Trạng thái",
    "room.assignee": "Người đảm nhận",
    "room.unassigned": "— Chưa giao —",
    "room.assignWake": "giao việc sẽ kích hoạt wake",
    "room.recordedNext": "Việc tiếp theo đã ghi",
    "room.dod": "Tiêu chí hoàn thành",
    "room.dodArtifact": "Đã xuất bản artifact vào kho chung",
    "room.artifacts": "Artifact",
    "room.noneYet": "Chưa có.",
    "room.thread": "Luồng cộng tác",
    "room.system": "Hệ thống",
    "room.patron": "Patron",
    "room.agent": "agent",
    "room.noMessages": "Chưa có tin nhắn.",
    "room.messagePlaceholder": "Nhắn trong phòng — dùng @Tên để đánh thức một agent…",
    "room.sendHint": "⌘/Ctrl + Enter để gửi · @mention đánh thức",
    "room.send": "Gửi",
    "room.awaitingReview": "Đang chờ bạn duyệt",
    "room.requestChanges": "Yêu cầu sửa lại",
    "room.approvePublish": "Duyệt & xuất bản",
    "room.liveTrace": "Theo dõi trực tiếp",
    "room.streaming": "● đang phát",
    "room.noRuns": "Chưa có lượt chạy. Đánh thức một agent để xem nó làm việc.",
    "room.failed": "Thất bại",
    "room.cannotStatus": "Không đổi được trạng thái",
    "room.pickAgent": "chọn agent",
    "room.wake": "Đánh thức",
    // Patron inbox (bilingual)
    "inbox.title": "Hộp thư Patron",
    "inbox.count": "{n} việc cần bạn",
    "inbox.subtitle": "Chỉ những việc cần quyết định của người: artifact chờ duyệt và việc bị chặn.",
    "inbox.empty": "Không có gì chờ bạn. Scriptorium đang yên tĩnh. ✦",
    "inbox.open": "Mở",
    "inbox.approve": "Duyệt",
    "inbox.reviewGroup": "Đang chờ bạn duyệt",
    "inbox.blockedGroup": "Đang bị chặn",
    // Validation / errors
    "err.required": "Trường này là bắt buộc",
    "err.invalidEmail": "Nhập email hợp lệ",
    "err.shortPassword": "Mật khẩu phải có ít nhất 8 ký tự",
    "err.noWorkspace": "Không tìm thấy không gian làm việc.",
    "err.failedLoad": "Tải thất bại",
    // Task status
    "status.backlog": "Chờ xử lý",
    "status.todo": "Cần làm",
    "status.in_progress": "Đang tiến hành",
    "status.in_review": "Đang duyệt",
    "status.blocked": "Bị chặn",
    "status.done": "Hoàn thành",
    "status.cancelled": "Đã hủy",
    // Liveness
    "liveness.online": "Online",
    "liveness.working": "Đang làm",
    "liveness.idle": "Nghỉ",
    "liveness.offline": "Ngoại tuyến",
    "liveness.hung": "Treo",
    // Relative time
    "time.secondsAgo": "{n} giây trước",
    "time.minutesAgo": "{n} phút trước",
    "time.hoursAgo": "{n} giờ trước",
    "time.daysAgo": "{n} ngày trước",
  },
} as const;

export type TranslationKey = keyof (typeof dict)["en"];

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

type Params = Record<string, string | number>;

interface I18nState {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: TranslationKey, params?: Params) => string;
  // Always-English lookup. The Patron Inbox view stays English regardless of `lang`.
  tEn: (key: TranslationKey, params?: Params) => string;
}

const I18nCtx = createContext<I18nState | null>(null);

function detectLang(): Lang {
  const stored = localStorage.getItem(LANG_KEY) as Lang | null;
  if (stored === "en" || stored === "vi") return stored;
  const nav = navigator.language?.toLowerCase() ?? "";
  return nav.startsWith("vi") ? "vi" : "en";
}

function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k) =>
    params[k] !== undefined ? String(params[k]) : `{${k}}`,
  );
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  useEffect(() => {
    localStorage.setItem(LANG_KEY, lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const t = useCallback(
    (key: TranslationKey, params?: Params) =>
      interpolate((dict[lang][key] ?? dict.en[key] ?? key) as string, params),
    [lang],
  );
  const tEn = useCallback(
    (key: TranslationKey, params?: Params) => interpolate((dict.en[key] ?? key) as string, params),
    [],
  );

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
