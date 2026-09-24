import type { UiLanguage } from '../../i18n/uiText';
import type { OnboardingRole } from './onboardingState';

export type OnboardingStep = {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  route?: string;
  target?: string;
  interactionHint?: string;
  advanceOnTargetClick?: boolean;
};

export type OnboardingCopy = {
  roleLabel: string;
  steps: OnboardingStep[];
};

type CommonCopy = {
  progress: string;
  skip: string;
  previous: string;
  next: string;
  finish: string;
  targetUnavailable: string;
  replay: string;
};

export const ONBOARDING_COMMON_COPY: Record<UiLanguage, CommonCopy> = {
  zh: {
    progress: '步骤 {current} / {total}',
    skip: '跳过导览',
    previous: '上一步',
    next: '下一步',
    finish: '完成导览',
    targetUnavailable: '当前尺寸下未显示该区域，你仍可继续下一步。',
    replay: '新手导览',
  },
  en: {
    progress: 'Step {current} of {total}',
    skip: 'Skip tour',
    previous: 'Back',
    next: 'Next',
    finish: 'Finish tour',
    targetUnavailable: 'This area is hidden at the current window size. You can still continue.',
    replay: 'Guided tour',
  },
};

const WORKSPACE_STEPS: Record<UiLanguage, OnboardingStep[]> = {
  zh: [
    {
      id: 'welcome',
      eyebrow: '普通用户 · 全模块导览',
      title: '先完成一次真实的投研动作',
      description: '接下来会依次进入首页、选股、持仓、AI 建议、回测和“更多”中的工具。每一步只讲一个核心用途，完成或跳过后都不会在下次登录时自动弹出。',
    },
    {
      id: 'analyze',
      eyebrow: '首页 · 发起分析',
      title: '从一只熟悉的股票开始',
      description: '输入代码或名称后点击“分析”，系统会生成可保存的结构化报告。现在只需点击输入框，不会自动提交任务。',
      route: '/',
      target: '[data-onboarding="home-stock-search"]',
      interactionHint: '点击高亮输入框继续',
      advanceOnTargetClick: true,
    },
    {
      id: 'home-workspace',
      eyebrow: '首页 · 组织工作',
      title: '看板、历史、自选与今日各司其职',
      description: '看板观察市场，历史切换已生成报告，自选集中跟踪股票，今日查看当天结果。后台分析不会锁住这些切换操作。',
      route: '/',
      target: '[data-onboarding="home-workspace-tabs"]',
    },
    {
      id: 'screening',
      eyebrow: '选股 · 发现机会',
      title: '先看热点，再组合筛选策略',
      description: '热点题材提供市场线索，策略负责把热度、行情与基本面条件转成候选股。实验结果只用于研究，不替代投资判断。',
      route: '/screening',
      target: '[data-onboarding="screening-hotspots"]',
    },
    {
      id: 'portfolio',
      eyebrow: '持仓 · 连接真实仓位',
      title: '账户视角决定收益与风险口径',
      description: '先选择账户与成本法，再查看权益、持仓盈亏和风险暴露。交易流水、资金变动和公司行动会共同影响持仓结果。',
      route: '/portfolio',
      target: '[data-onboarding="portfolio-overview"]',
    },
    {
      id: 'decision-signals',
      eyebrow: 'AI 建议 · 沉淀结论',
      title: '把一次分析变成可跟踪的信号',
      description: '按股票筛选建议，记录采纳、忽略或待观察状态，并在后续行情中复核结果；这里适合管理结论，而不是重新生成完整报告。',
      route: '/decision-signals',
      target: '[data-onboarding="decision-signal-context"]',
    },
    {
      id: 'backtest',
      eyebrow: '回测 · 验证判断',
      title: '用历史结果检验策略稳定性',
      description: '选择股票、评估窗口、市场阶段和日期范围后运行回测。先观察样本数量和胜率，再解释单次收益。',
      route: '/backtest',
      target: '[data-onboarding="backtest-controls"]',
    },
    {
      id: 'alerts',
      eyebrow: '更多 · 告警中心',
      title: '让关键变化主动找到你',
      description: '创建价格、指标、自选或持仓联动规则，并通过测试确认条件是否正确。启用后的规则会持续评估并保留触发记录。',
      route: '/alerts',
      target: '[data-onboarding="alerts-workspace"]',
    },
    {
      id: 'usage',
      eyebrow: '更多 · 用量统计',
      title: '看清模型调用和 Token 去向',
      description: '按时间范围查看总调用量、模型分布和调用类型，便于识别异常消耗并调整模型与任务频率。',
      route: '/usage',
      target: '[data-onboarding="usage-overview"]',
    },
    {
      id: 'settings',
      eyebrow: '更多 · 系统设置',
      title: '配置按类别集中管理',
      description: '通过左侧分类定位数据源、模型、调度与系统能力。修改只保存在草稿中，点击保存后才会写入配置。',
      route: '/settings',
      target: '[data-onboarding="settings-navigation"]',
    },
    {
      id: 'assistant',
      eyebrow: '最后一步 · 随时追问',
      title: '有具体问题，就直接问股',
      description: '问股适合连续追问；首页“分析”适合生成正式报告。点击右下角问股入口即可完成导览。',
      route: '/',
      target: '[data-onboarding="stock-assistant-launcher"]',
      interactionHint: '点击问股，完成导览',
      advanceOnTargetClick: true,
    },
  ],
  en: [
    {
      id: 'welcome',
      eyebrow: 'Member · Full workspace tour',
      title: 'Complete one real research action first',
      description: 'We will visit Home, Screening, Portfolio, AI Signals, Backtest, and the tools under More. Each step covers one purpose, and the tour will not reopen automatically after completion or skip.',
    },
    {
      id: 'analyze',
      eyebrow: 'Home · Start analysis',
      title: 'Start with a stock you know',
      description: 'Enter a symbol or name and choose Analyze to create a saved, structured report. Click the field now; no task will be submitted.',
      route: '/',
      target: '[data-onboarding="home-stock-search"]',
      interactionHint: 'Click the highlighted field to continue',
      advanceOnTargetClick: true,
    },
    {
      id: 'home-workspace',
      eyebrow: 'Home · Organize work',
      title: 'Dashboard, History, Watchlist, and Today have distinct jobs',
      description: 'Use Dashboard for the market, History for saved reports, Watchlist for tracked names, and Today for current results. Background analysis never needs to block these tabs.',
      route: '/',
      target: '[data-onboarding="home-workspace-tabs"]',
    },
    {
      id: 'screening',
      eyebrow: 'Screening · Find candidates',
      title: 'Read market themes before combining strategies',
      description: 'Themes provide context; strategies convert heat, price action, and fundamentals into candidates. Experimental output supports research, not investment decisions.',
      route: '/screening',
      target: '[data-onboarding="screening-hotspots"]',
    },
    {
      id: 'portfolio',
      eyebrow: 'Portfolio · Add real position context',
      title: 'Account scope defines return and risk',
      description: 'Choose an account and cost method before reading equity, holding P/L, and exposure. Trades, cash movements, and corporate actions all affect the result.',
      route: '/portfolio',
      target: '[data-onboarding="portfolio-overview"]',
    },
    {
      id: 'decision-signals',
      eyebrow: 'AI Signals · Retain decisions',
      title: 'Turn one report into a trackable signal',
      description: 'Filter by stock, record whether a signal is adopted or ignored, and review the later outcome. This page manages conclusions rather than creating a full report.',
      route: '/decision-signals',
      target: '[data-onboarding="decision-signal-context"]',
    },
    {
      id: 'backtest',
      eyebrow: 'Backtest · Validate calls',
      title: 'Test whether a decision holds up historically',
      description: 'Set the stock, evaluation window, market phase, and date range. Read sample size and win rate before interpreting a single return.',
      route: '/backtest',
      target: '[data-onboarding="backtest-controls"]',
    },
    {
      id: 'alerts',
      eyebrow: 'More · Alert center',
      title: 'Let important changes come to you',
      description: 'Create price, indicator, watchlist, or portfolio-linked rules and test their conditions. Enabled rules continue evaluating and retain trigger history.',
      route: '/alerts',
      target: '[data-onboarding="alerts-workspace"]',
    },
    {
      id: 'usage',
      eyebrow: 'More · Usage',
      title: 'See where model calls and tokens go',
      description: 'Review totals, model distribution, and call types by period to spot unusual consumption and tune model or task frequency.',
      route: '/usage',
      target: '[data-onboarding="usage-overview"]',
    },
    {
      id: 'settings',
      eyebrow: 'More · Settings',
      title: 'Manage configuration by category',
      description: 'Use the category rail to find data sources, models, schedules, and system capabilities. Edits remain drafts until you save them.',
      route: '/settings',
      target: '[data-onboarding="settings-navigation"]',
    },
    {
      id: 'assistant',
      eyebrow: 'Final step · Follow up anytime',
      title: 'Ask AI when the question is specific',
      description: 'Ask Stock is for a conversation; Analyze on Home creates a formal report. Open Ask Stock to finish the tour.',
      route: '/',
      target: '[data-onboarding="stock-assistant-launcher"]',
      interactionHint: 'Open Ask Stock to finish',
      advanceOnTargetClick: true,
    },
  ],
};

const AUDITOR_STEPS: Record<UiLanguage, OnboardingStep[]> = {
  zh: [
    {
      id: 'welcome',
      eyebrow: '审计员 · 只读工作区',
      title: '你的任务是核对，不是修改',
      description: '审计员只读取安全与管理日志。用户邀请、角色调整和系统配置不会出现在你的操作范围内。',
    },
    {
      id: 'logs',
      eyebrow: '第一步 · 识别记录',
      title: '从时间、操作、资源和结果开始',
      description: '每一行对应一次关键管理或安全操作。先确认结果，再结合资源与时间定位需要复核的行为。',
      target: '[data-onboarding="admin-audit-logs"]',
    },
    {
      id: 'refresh',
      eyebrow: '第二步 · 获取最新状态',
      title: '复核前先刷新审计记录',
      description: '点击刷新会重新读取最新日志，不会修改平台数据。',
      target: '[data-onboarding="admin-refresh"]',
      interactionHint: '点击刷新，完成导览',
      advanceOnTargetClick: true,
    },
  ],
  en: [
    {
      id: 'welcome',
      eyebrow: 'Auditor · Read-only workspace',
      title: 'Your job is to verify, not modify',
      description: 'Auditors only read security and administration logs. Invitations, role changes, and system configuration remain outside your scope.',
    },
    {
      id: 'logs',
      eyebrow: 'Step one · Read the record',
      title: 'Start with time, action, resource, and outcome',
      description: 'Each row represents a key security or administration action. Check the outcome first, then use its resource and time to investigate.',
      target: '[data-onboarding="admin-audit-logs"]',
    },
    {
      id: 'refresh',
      eyebrow: 'Step two · Get current state',
      title: 'Refresh before you review',
      description: 'Refresh reads the latest logs without changing platform data.',
      target: '[data-onboarding="admin-refresh"]',
      interactionHint: 'Refresh to finish the tour',
      advanceOnTargetClick: true,
    },
  ],
};

const ADMIN_STEPS: Record<UiLanguage, OnboardingStep[]> = {
  zh: [
    {
      id: 'welcome',
      eyebrow: '平台管理员 · 约 60 秒',
      title: '先掌握三项管理职责',
      description: '平台管理员负责用户状态、最小权限邀请和审计追踪。产品工作台与管理后台使用相互独立的登录会话。',
    },
    {
      id: 'users',
      eyebrow: '第一步 · 用户治理',
      title: '在这里核对角色与账号状态',
      description: '角色变化会撤销用户已有会话。平台所有者受到保护，不会通过这里被降权或停用。',
      target: '[data-onboarding="admin-users"]',
    },
    {
      id: 'role',
      eyebrow: '第二步 · 最小权限',
      title: '邀请前，先选对角色',
      description: '普通用户进入投研工作台；审计员只读日志；平台管理员可管理用户与系统。点击角色选择器查看选项，不会立即生成邀请。',
      target: '[data-onboarding="admin-role-select"]',
      interactionHint: '点击角色选择器继续',
      advanceOnTargetClick: true,
    },
    {
      id: 'audit',
      eyebrow: '第三步 · 留痕复核',
      title: '关键管理动作都会留下记录',
      description: '完成邀请、角色调整或账号停用后，到这里核对操作结果。至此你已经掌握管理员的最短工作链路。',
      target: '[data-onboarding="admin-audit-logs"]',
    },
  ],
  en: [
    {
      id: 'welcome',
      eyebrow: 'Platform administrator · About 60 seconds',
      title: 'Learn the three administration duties',
      description: 'Platform administrators manage account state, least-privilege invitations, and audit trails. Product and admin sessions are separate.',
    },
    {
      id: 'users',
      eyebrow: 'Step one · User governance',
      title: 'Review roles and account status here',
      description: 'Changing a role revokes the user’s existing sessions. The platform owner is protected from role changes and suspension here.',
      target: '[data-onboarding="admin-users"]',
    },
    {
      id: 'role',
      eyebrow: 'Step two · Least privilege',
      title: 'Choose the right role before inviting',
      description: 'Members use research tools, auditors only read logs, and platform administrators manage users and the system. Open the role menu to continue.',
      target: '[data-onboarding="admin-role-select"]',
      interactionHint: 'Open the role selector to continue',
      advanceOnTargetClick: true,
    },
    {
      id: 'audit',
      eyebrow: 'Step three · Verify the trail',
      title: 'Key administration actions leave a record',
      description: 'After invitations, role changes, or suspensions, verify the outcome here. You now know the shortest administrator workflow.',
      target: '[data-onboarding="admin-audit-logs"]',
    },
  ],
};

type OnboardingCopyOptions = {
  includeSettings?: boolean;
};

export function getOnboardingCopy(
  role: OnboardingRole,
  language: UiLanguage,
  options: OnboardingCopyOptions = {},
): OnboardingCopy {
  if (role === 'auditor') {
    return { roleLabel: language === 'en' ? 'Auditor' : '审计员', steps: AUDITOR_STEPS[language] };
  }
  if (role === 'platform_admin') {
    return { roleLabel: language === 'en' ? 'Platform administrator' : '平台管理员', steps: ADMIN_STEPS[language] };
  }
  const workspaceSteps = options.includeSettings
    ? WORKSPACE_STEPS[language]
    : WORKSPACE_STEPS[language].filter((step) => step.id !== 'settings');
  return { roleLabel: language === 'en' ? 'Member' : '普通用户', steps: workspaceSteps };
}
