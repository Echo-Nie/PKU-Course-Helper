import React from 'react';
import { sleepProtectionNotice } from './state.js';

export default function SleepNotice({ state, power }) {
  const notice = sleepProtectionNotice(state, power);
  if (!notice) return null;
  return <p className={`runtime-power${notice.warning ? ' warning' : power?.active ? ' enabled' : ''}`} role={notice.warning ? 'alert' : 'status'}
    title="选课期间启用专用电源方案，接电和电池下均合盖不睡眠，关闭自动睡眠、休眠和可控制的睡眠入口，并持续复查。运行期间屏幕可能保持点亮，停止后恢复原方案。请保持供电和散热；关机、重启、断电或系统强制保护仍会中断。">
    {notice.text}
  </p>;
}
