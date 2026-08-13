import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

export type Lang = 'zh' | 'en';

type Dict = Record<string, { zh: string; en: string }>;

const DICT: Dict = {
  // App
  'app.title': { zh: 'XTAO Agent', en: 'XTAO Agent' },
  'app.subtitle': { zh: '基于 G4C 方法论的可执行 Agent 规划引擎', en: 'Executable Agent Planning Engine based on G4C Methodology' },

  // Chat
  'chat.placeholder': { zh: '输入你的任务…', en: 'Enter your task…' },
  'chat.send': { zh: '发送', en: 'Send' },
  'chat.emptyTitle': { zh: '开始对话', en: 'Start a Conversation' },
  'chat.emptyDesc': { zh: '输入一个任务，XTAO 将自动生成 Plan 并逐步执行', en: 'Enter a task and XTAO will automatically generate a Plan and execute it step by step' },
  'chat.examples': { zh: '示例任务', en: 'Example tasks' },
  'chat.thinking': { zh: 'XTAO 正在规划与执行…', en: 'XTAO is planning and executing…' },
  'chat.error': { zh: '调用失败', en: 'Request failed' },

  // Phase
  'phase.generate': { zh: '生成 Plan', en: 'Generating Plan' },
  'phase.verify': { zh: '评估 Plan', en: 'Verifying Plan' },
  'phase.execute': { zh: '执行 Plan', en: 'Executing Plan' },
  'live.steps': { zh: '步', en: 'steps' },
  'live.verifyScore': { zh: '验证分数', en: 'Score' },
  'live.passed': { zh: '通过', en: 'Passed' },
  'live.notPassed': { zh: '未通过', en: 'Failed' },

  // Step status
  'step.pending': { zh: '待执行', en: 'Pending' },
  'step.running': { zh: '执行中', en: 'Running' },
  'step.done': { zh: '完成', en: 'Done' },
  'step.failed': { zh: '失败', en: 'Failed' },

  // Timing
  'timing.gen': { zh: '生成', en: 'Gen' },
  'timing.verify': { zh: '验证', en: 'Verify' },
  'timing.llm': { zh: 'LLM', en: 'LLM' },
  'timing.ck': { zh: '检查', en: 'CK' },
  'timing.total': { zh: '总计', en: 'Total' },

  // Result
  'status.completed': { zh: '已完成', en: 'Completed' },
  'status.failed': { zh: '失败', en: 'Failed' },
  'status.aborted': { zh: '中止', en: 'Aborted' },
  'status.clarify_needed': { zh: '需澄清', en: 'Clarify Needed' },
  'result.errors': { zh: '错误：', en: 'Errors:' },
  'result.finalOutput': { zh: '最终输出', en: 'Final Output' },
  'result.showG4C': { zh: '展开 G4C 与步骤轨迹', en: 'Show G4C & Step Trace' },
  'result.hideG4C': { zh: '收起', en: 'Hide' },
  'result.clarify': { zh: '需要澄清', en: 'Clarification needed' },

  // Settings
  'settings.title': { zh: '运行配置', en: 'Configuration' },
  'settings.desc': { zh: '调整编排引擎参数', en: 'Adjust orchestration engine parameters' },
  'settings.useTao': { zh: '启用 TAO 步骤级执行', en: 'Enable TAO step-level execution' },
  'settings.skipCheckpoint': { zh: '跳过 Checkpoint（加速）', en: 'Skip Checkpoint (Faster)' },
  'settings.tccReplan': { zh: '启用 TCC Replan（高风险场景）', en: 'Enable TCC Replan (High-risk)' },
  'settings.maxReplan': { zh: '最大 Replan 次数', en: 'Max Replan Count' },
  'settings.verifyThreshold': { zh: '验证阈值', en: 'Verification Threshold' },
  'settings.taoMaxLoops': { zh: 'TAO 最大循环数', en: 'TAO Max Loops' },

  // Step trace
  'trace.noRecords': { zh: '无步骤记录', en: 'No step records' },
  'trace.ckPassed': { zh: 'checkpoint 通过', en: 'checkpoint passed' },
  'trace.ckFailed': { zh: 'checkpoint 未通过', en: 'checkpoint failed' },
  'trace.replanTrigger': { zh: '纠偏', en: 'Correction' },
  'trace.replanTriggered': { zh: '触发 Replan', en: 'triggered Replan' },
  'trace.rootCause': { zh: '根因步骤:', en: 'Root cause step:' },
  'trace.output': { zh: '输出', en: 'Output' },

  // G4C
  'g4c.goal': { zh: 'Goal · 目标', en: 'Goal' },
  'g4c.context': { zh: 'Context · 上下文', en: 'Context' },
  'g4c.choice': { zh: 'Choice · 路径选择', en: 'Choice' },
  'g4c.checkpoint': { zh: 'Checkpoint · 检查点', en: 'Checkpoint' },
  'g4c.correction': { zh: 'Correction · 纠偏', en: 'Correction' },
  'g4c.successCriteria': { zh: '成功标准', en: 'Success Criteria' },
  'g4c.known': { zh: '已知', en: 'Known' },
  'g4c.missing': { zh: '缺失', en: 'Missing' },
  'g4c.hardConstraints': { zh: '硬约束', en: 'Hard Constraints' },
  'g4c.softConstraints': { zh: '软约束', en: 'Soft Constraints' },
  'g4c.reason': { zh: '理由', en: 'Reason' },
  'g4c.none': { zh: '无', en: 'None' },
  'g4c.steps': { zh: '步骤', en: 'Steps' },
  'g4c.checks': { zh: '检查', en: 'Checks' },
};

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const Ctx = createContext<I18nCtx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('zh');
  const t = useCallback(
    (key: string) => {
      const entry = DICT[key];
      if (!entry) return key;
      return entry[lang];
    },
    [lang],
  );
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useI18n must be used within I18nProvider');
  return ctx;
}
