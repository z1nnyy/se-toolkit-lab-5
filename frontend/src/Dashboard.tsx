import { useState, useEffect } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
} from 'chart.js'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
)

const DEFAULT_LAB = 'lab-04'

interface ScoreBucket {
  bucket: string
  count: number
}

interface PassRate {
  task: string
  avg_score: number
  attempts: number
}

interface TimelinePoint {
  date: string
  submissions: number
}

interface DashboardProps {
  token: string
}

async function fetchWithAuth<T>(url: string, token: string): Promise<T> {
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<T>
}

type DashboardFetchState =
  | { status: 'loading' }
  | {
      status: 'success'
      lab: string
      scores: ScoreBucket[]
      passRates: PassRate[]
      timeline: TimelinePoint[]
    }
  | { status: 'error'; message: string }

export function Dashboard({ token }: DashboardProps) {
  const [lab, setLab] = useState(DEFAULT_LAB)
  const [fetchState, setFetchState] = useState<DashboardFetchState>({
    status: 'loading',
  })

  useEffect(() => {
    if (!token) return

    const requestedLab = lab
    const params = new URLSearchParams({ lab: requestedLab })
    const base = '/analytics'

    Promise.all([
      fetchWithAuth<ScoreBucket[]>(`${base}/scores?${params}`, token),
      fetchWithAuth<PassRate[]>(`${base}/pass-rates?${params}`, token),
      fetchWithAuth<TimelinePoint[]>(`${base}/timeline?${params}`, token),
    ])
      .then(([scores, passRates, timeline]) => {
        setFetchState((prev) => {
          if (prev.status === 'success' && prev.lab !== requestedLab) return prev
          return { status: 'success', lab: requestedLab, scores, passRates, timeline }
        })
      })
      .catch((err: Error) => {
        setFetchState((prev) => {
          if (prev.status === 'success' && prev.lab !== requestedLab) return prev
          return { status: 'error', message: err.message }
        })
      })
  }, [token, lab])

  if (fetchState.status === 'loading') return <p>Loading...</p>
  if (fetchState.status === 'error') return <p>Error: {fetchState.message}</p>
  if (fetchState.lab !== lab) return <p>Loading...</p>

  const { scores, passRates, timeline } = fetchState

  const barData = {
    labels: scores.map((s) => s.bucket),
    datasets: [
      {
        label: 'Count',
        data: scores.map((s) => s.count),
        backgroundColor: 'rgba(54, 162, 235, 0.5)',
        borderColor: 'rgb(54, 162, 235)',
        borderWidth: 1,
      },
    ],
  }

  const lineData = {
    labels: timeline.map((t) => t.date),
    datasets: [
      {
        label: 'Submissions',
        data: timeline.map((t) => t.submissions),
        borderColor: 'rgb(75, 192, 192)',
        backgroundColor: 'rgba(75, 192, 192, 0.2)',
        tension: 0.1,
      },
    ],
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
    },
  }

  const labOptions = ['lab-01', 'lab-02', 'lab-03', 'lab-04', 'lab-05']

  return (
    <div className="dashboard">
      <div className="dashboard-controls">
        <label htmlFor="lab-select">Lab:</label>
        <select
          id="lab-select"
          value={lab}
          onChange={(e) => setLab(e.target.value)}
        >
          {labOptions.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </div>

      <div className="dashboard-charts">
        <div className="chart-container">
          <h3>Score Distribution</h3>
          <div className="chart-wrapper">
            <Bar data={barData} options={chartOptions} />
          </div>
        </div>

        <div className="chart-container">
          <h3>Submissions Over Time</h3>
          <div className="chart-wrapper">
            <Line data={lineData} options={chartOptions} />
          </div>
        </div>
      </div>

      <div className="dashboard-table">
        <h3>Pass Rates per Task</h3>
        <table>
          <thead>
            <tr>
              <th>Task</th>
              <th>Avg Score</th>
              <th>Attempts</th>
            </tr>
          </thead>
          <tbody>
            {passRates.map((row) => (
              <tr key={row.task}>
                <td>{row.task}</td>
                <td>{row.avg_score.toFixed(1)}</td>
                <td>{row.attempts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}