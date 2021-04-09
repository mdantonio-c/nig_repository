import { Component, OnInit } from "@angular/core";
import { DataService } from "../../services/data.service";
import { Stats } from "../../types";
import { Observable } from "rxjs"

@Component({
  selector: "nig-welcome",
  templateUrl: "./welcome.component.html"
})
export class WelcomeComponent implements OnInit {
  stats$: Observable<Stats>;

  constructor(private dataService: DataService) {
  }

  ngOnInit() {
    this.stats$ = this.dataService.getStats();
  }
}
