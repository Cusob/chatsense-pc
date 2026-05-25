from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib

matplotlib.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False


class TrendChart(FigureCanvas):
    """Score trend line chart showing historical analysis results."""

    def __init__(self, parent=None, width=4, height=2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)
        self.setParent(parent)

    def render(self, history: list[dict]):
        """history: list of {timestamp: int, overall: int} sorted by timestamp ASC."""
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        if not history or len(history) < 2:
            ax.text(
                0.5, 0.5, "数据不足，需要至少2次分析结果",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=9, color="#999",
            )
            self.draw()
            return

        timestamps = range(len(history))
        scores = [h["overall"] for h in history]

        ax.plot(timestamps, scores, marker="o", color="#2196F3", linewidth=1.5, markersize=4)
        ax.fill_between(timestamps, scores, alpha=0.1, color="#2196F3")

        ax.set_ylim(0, 100)
        ax.set_ylabel("综合分", fontsize=8)
        ax.set_xlabel("分析次数", fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)

        # Color-coded background zones
        ax.axhspan(0, 35, alpha=0.05, color="#E53935")
        ax.axhspan(35, 40, alpha=0.05, color="#FFA726")
        ax.axhspan(40, 75, alpha=0.08, color="#43A047")
        ax.axhspan(75, 90, alpha=0.05, color="#FFA726")
        ax.axhspan(90, 100, alpha=0.05, color="#E53935")

        self.fig.tight_layout(pad=1.5)
        self.draw()

    def clear_chart(self):
        self.fig.clear()
        self.draw()
