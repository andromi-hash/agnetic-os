package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "agneticctl",
	Short: "Agnetic OS CLI",
	Long:  "Agnetic OS - a native AI operating system for complex system control",
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Println("Agnetic OS CLI")
	},
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}

func init() {
	rootCmd.AddCommand(versionCmd)
}
