// Every tool call of a run, from the database (Phase 11): timing, status, security flags.

import { StatusBadge } from "@/components/ui";

export default function RunHistory({ history }) {
  if (!history?.tool_logs?.length) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Step</th>
            <th>Tool</th>
            <th>Attempt</th>
            <th>Status</th>
            <th className="num">Time</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {history.tool_logs.map((log, index) => {
            const flags = log.output_data?.security_flags || [];
            return (
              <tr key={`${log.step_key}-${log.attempt}-${index}`}>
                <td>{log.step_key}</td>
                <td><code>{log.tool_name}</code></td>
                <td>#{log.attempt}</td>
                <td><StatusBadge status={log.status} /></td>
                <td className="num">{log.execution_time_ms ?? 0} ms</td>
                <td className="small">
                  {flags.length > 0 && <span className="error-text">Security flags: {flags.join(", ")}. </span>}
                  {log.error}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
