import asyncio
import json
import time
from datetime import datetime
import statistics
from pathlib import Path
import sys
import cProfile
import pstats
import io
from typing import List, Dict, Tuple
import logging
from dotenv import load_dotenv
import os


# Import the original code
from benchmarked_main import ApplicationRunner

class IterationRunner:
    def __init__(self, num_iterations: int, scenario: str = "small"):
        self.num_iterations = num_iterations
        self.results = []
        self.setup_logging()
        self.profile_dir = Path(f'profiling_results/{scenario}')
        self.profile_dir.mkdir(exist_ok=True, parents=True)
        self.scenario = scenario
        
    def setup_logging(self):
        """Setup logging for iteration runs"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            filename=f'iteration_runs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
            filemode='w'
        )
        self.logger = logging.getLogger("IterationRunner")

    async def run_single_iteration(self, iteration: int) -> Tuple[Dict, pstats.Stats]:
        """Run a single iteration of the timetabling system with profiling"""
        self.logger.info(f"Starting iteration {iteration}")
        start_time = time.time()
        
        # Create profiler for this iteration
        profiler = cProfile.Profile()
        
        try:
            # Create new runner instance for this iteration
            runner = ApplicationRunner(self.xmpp_server, self.password, scenario=self.scenario)
            
            # Start profiling and run the system
            profiler.enable()
            await runner.run()
            profiler.disable()
            
            # Calculate metrics
            duration = time.time() - start_time
            
            # Get metrics from storage if available
            prof_assignments = 0
            room_utilization = 0
            
            if runner.app_agent and runner.app_agent.prof_storage:
                prof_assignments = runner.app_agent.prof_storage.get_pending_update_count()
            
            if runner.app_agent and runner.app_agent.room_storage:
                room_utilization = runner.app_agent.room_storage.get_pending_update_count()
            
            result = {
                "iteration": iteration,
                "duration": duration,
                "professor_assignments": prof_assignments,
                "room_utilization": room_utilization,
                "status": "success"
            }
            
            self.logger.info(f"Iteration {iteration} completed in {duration:.2f} seconds")
            
        except Exception as e:
            self.logger.error(f"Error in iteration {iteration}: {str(e)}")
            result = {
                "iteration": iteration,
                "duration": time.time() - start_time,
                "status": "error",
                "error": str(e)
            }
            
        # Create stats object from profiler
        stats = pstats.Stats(profiler)
        
        # Ensure cleanup between iterations
        await asyncio.sleep(2)
        return result, stats

    def save_profile_stats(self, stats: pstats.Stats, iteration: int):
        """Save profiling statistics to files"""
        # Save full stats
        current_time = datetime.now().strftime('%d-%m-%Y_%H-%M-%S')
        stats_file = self.profile_dir / f"profile_stats_{iteration}_{current_time}.prof"
        stats.dump_stats(str(stats_file))

        # Save readable text summary
        summary_file = self.profile_dir / f"profile_summary_{iteration}_{current_time}.txt"

        with io.StringIO() as stream:
            # Sort by cumulative time and print top 50 functions
            stats.sort_stats('cumulative')
            stats.stream = stream
            stats.print_stats(50)
            
            # Also include callers for top 20 functions
            stats.print_callers(20)
            
            with open(summary_file, 'w') as f:
                f.write(stream.getvalue())

    async def run_iterations(self):
        """Run all iterations and collect results with profiling"""
        self.logger.info(f"Starting {self.num_iterations} iterations")
        
        # Load environment variables
        load_dotenv()
        self.xmpp_server = os.getenv("XMPP_SERVER")
        self.password = os.getenv("AGENT_PASSWORD")
        
        if not self.xmpp_server or not self.password:
            self.logger.error("XMPP_SERVER and AGENT_PASSWORD must be set in .env file")
            return
        
        # Run iterations
        for i in range(self.num_iterations):
            result, stats = await self.run_single_iteration(i + 1)
            self.results.append(result)
            
            # Save profiling results
            self.save_profile_stats(stats, i + 1)
            
            # Save intermediate results
            self.save_results()
            
            # Brief pause between iterations
            await asyncio.sleep(5)
            
        self.analyze_results()

    def save_results(self):
        """Save results to JSON file"""
        path_json = Path(f'results_json_profiling/{self.scenario}')
        path_json.mkdir(exist_ok=True, parents=True)
        output_file = path_json / f"iteration_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)

    def analyze_results(self):
        """Analyze and print summary statistics"""
        successful_runs = [r for r in self.results if r["status"] == "success"]
        failed_runs = [r for r in self.results if r["status"] == "error"]
        
        if successful_runs:
            durations = [r["duration"] for r in successful_runs]
            prof_assignments = [r.get("professor_assignments", 0) for r in successful_runs]
            room_utilization = [r.get("room_utilization", 0) for r in successful_runs]
            
            summary = {
                "total_iterations": self.num_iterations,
                "successful_runs": len(successful_runs),
                "failed_runs": len(failed_runs),
                "average_duration": statistics.mean(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "std_dev_duration": statistics.stdev(durations) if len(durations) > 1 else 0,
                "avg_professor_assignments": statistics.mean(prof_assignments),
                "avg_room_utilization": statistics.mean(room_utilization)
            }
            
            # Print summary
            print("\nIteration Summary:")
            print("-" * 50)
            print(f"Total Iterations: {summary['total_iterations']}")
            print(f"Successful Runs: {summary['successful_runs']}")
            print(f"Failed Runs: {summary['failed_runs']}")
            print(f"Average Duration: {summary['average_duration']:.2f} seconds")
            print(f"Min Duration: {summary['min_duration']:.2f} seconds")
            print(f"Max Duration: {summary['max_duration']:.2f} seconds")
            print(f"Std Dev Duration: {summary['std_dev_duration']:.2f} seconds")
            print(f"Avg Professor Assignments: {summary['avg_professor_assignments']:.2f}")
            print(f"Avg Room Utilization: {summary['avg_room_utilization']:.2f}")
            
            json_summary_path = Path(f'iteration_summary/{self.scenario}')
            json_summary_path.mkdir(exist_ok=True, parents=True)
            # Save summary
            with open(f"{json_summary_path}/summary.json", 'w') as f:
                json.dump(summary, f, indent=2)
        else:
            print("No successful iterations to analyze")

        # Print profiling file locations
        print("\nProfiling Results:")
        print("-" * 50)
        print(f"Detailed profiling results saved in: {self.profile_dir}/")
        print("Files:")
        print("- profile_stats_N.prof: Raw profiling data for iteration N")
        print("- profile_summary_N.txt: Human-readable summary for iteration N")

async def main(iterations: int = 1, scenario : str = "small"):
    runner = IterationRunner(num_iterations=iterations, scenario=scenario)
    await runner.run_iterations()

if __name__ == "__main__":
    import argparse

    try:
        # Check for command line arguments
        parser = argparse.ArgumentParser(description="Run iterations of the timetabling system with profiling")
        parser.add_argument("--iterations", type=int, default=1, help="Number of iterations to run")
        parser.add_argument("--scenario", type=str, default="small", help="Scenario to use for the iterations (small, medium, full)")
        args = parser.parse_args()
        
        iterations = args.iterations
        scenario = args.scenario

        print(f"Running {iterations} iterations with scenario '{scenario}'")
        
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)