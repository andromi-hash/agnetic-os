package cmd

import (
	"fmt"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

var pingCmd = &cobra.Command{
	Use:   "ping",
	Short: "Ping the NATS agent bus",
	Run: func(cmd *cobra.Command, args []string) {
		nc, err := nats.Connect("127.0.0.1:4222", nats.Timeout(3*time.Second))
		if err != nil {
			fmt.Printf("NATS connection failed: %v\n", err)
			return
		}
		defer nc.Close()

		err = nc.Publish("agnetic.agent.proxy.status", []byte(`{"status":"ok","agent":"cli"}`))
		if err != nil {
			fmt.Printf("Publish failed: %v\n", err)
			return
		}

		fmt.Println("NATS bus OK — connected and published status message")
	},
}

func init() {
	rootCmd.AddCommand(pingCmd)
}
