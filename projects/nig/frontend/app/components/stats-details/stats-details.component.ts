import { Component, OnInit, Input } from "@angular/core";
import {ExtendedStats, Stats} from "../../types";
import { DataService } from "../../services/data.service";
import { Observable } from "rxjs";

@Component({
  selector: "nig-stats-details",
  templateUrl: "./stats-details.component.html"
})
export class StatsDetailsComponent implements OnInit {
  @Input() extended: boolean = false;
  stats$: Observable<Stats | ExtendedStats>;

  constructor(private dataService: DataService) {
  }

  ngOnInit() {
    this.stats$ = this.dataService.getStats(this.extended);
  }

}
