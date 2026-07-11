package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"time"

	"github.com/spf13/cobra"
)

var systemCmd = &cobra.Command{
	Use:   "system",
	Short: "System health commands",
}

var healthCmd = &cobra.Command{
	Use:   "health",
	Short: "Show system health overview",
	Run: func(cmd *cobra.Command, args []string) {
		hostname, _ := os.Hostname()
		fmt.Printf("Host: %s\n", hostname)
		fmt.Printf("OS:  %s/%s\n", runtime.GOOS, runtime.GOARCH)
		fmt.Printf("Time: %s\n", time.Now().Format(time.RFC1123))

		if out, err := exec.Command("sh", "-c", "free -h | head -2").Output(); err == nil {
			fmt.Printf("\n%s", out)
		}
		if out, err := exec.Command("sh", "-c", "df -h / | tail -1").Output(); err == nil {
			fmt.Printf("Disk: %s", out)
		}
	},
}

func init() {
	rootCmd.AddCommand(systemCmd)
	systemCmd.AddCommand(healthCmd)
}
